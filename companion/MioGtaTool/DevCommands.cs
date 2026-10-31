using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.Json;
using CodeWalker.GameFiles;
using CodeWalker.Utils;

namespace MioGtaTool
{
    /// <summary>
    /// dev-make-rpf : COMMANDE DE TEST UNIQUEMENT. Construit une fausse arborescence "GTA V" avec des archives RPF
    /// non chiffrees (OPEN, format OpenIV) contenant des YTD generes a partir de DDS de test, un dlclist.xml, etc.
    /// Elle sert aux tests automatises (homonymes, priorite DLC, textures manquantes) sans fichiers Rockstar.
    /// Les fichiers produits ne sont pas lisibles sans --no-keys et ne doivent jamais remplacer une vraie installation.
    ///
    /// --spec {"archives":[{"path":"x64a.rpf","files":[{"path":"levels/a/a_txd.ytd","ytd":[{"name":"t","dds":"/x.dds"}]},
    ///                                                {"path":"common/data/dlclist.xml","text":"..."},
    ///                                                {"path":"levels/a/a.ytyp","bin":"/x.ytyp"}],
    ///          "archives":[{"path":"levels/sub.rpf","files":[...]}]}]}
    /// </summary>
    public static class DevMakeRpfCommand
    {
        public class TexSpec { public string name { get; set; } public string dds { get; set; } }
        public class FileSpec { public string path { get; set; } public List<TexSpec> ytd { get; set; } public string text { get; set; } public string bin { get; set; } }
        public class ArchiveSpec { public string path { get; set; } public List<FileSpec> files { get; set; } public List<ArchiveSpec> archives { get; set; } }
        public class Spec { public List<ArchiveSpec> archives { get; set; } }

        public static int Run(Args args)
        {
            var spec = JsonSerializer.Deserialize<Spec>(File.ReadAllText(args.Require("spec")));
            var root = Path.GetFullPath(args.Require("out"));
            RpfManager.IsGen9 = false;
            Directory.CreateDirectory(root);
            int n = 0;
            foreach (var a in spec.archives ?? new List<ArchiveSpec>())
            {
                var full = Path.Combine(root, a.path.Replace('\\', '/'));
                Directory.CreateDirectory(Path.GetDirectoryName(full));
                if (File.Exists(full)) File.Delete(full);
                File.Create(full).Dispose();
                var rf = new RpfFile(full, a.path.Replace('/', '\\'));
                using (var fs = File.Open(full, FileMode.Open, FileAccess.ReadWrite))
                using (var bw = new BinaryWriter(fs))
                {
                    var m = typeof(RpfFile).GetMethod("WriteNewArchive", BindingFlags.NonPublic | BindingFlags.Instance);
                    if (m == null) throw new ToolException("API CodeWalker inattendue (WriteNewArchive).");
                    m.Invoke(rf, new object[] { bw, RpfEncryption.OPEN });
                }
                Fill(rf.Root, a);
                n++;
            }
            Out.Result(new { root, archives = n });
            return 0;
        }

        private static RpfDirectoryEntry EnsureDir(RpfDirectoryEntry dir, string relDir)
        {
            foreach (var part in relDir.Split(new[] { '/', '\\' }, StringSplitOptions.RemoveEmptyEntries))
            {
                var existing = dir.Directories.FirstOrDefault(d => d.NameLower == part.ToLowerInvariant());
                dir = existing ?? RpfFile.CreateDirectory(dir, part);
            }
            return dir;
        }

        private static void Fill(RpfDirectoryEntry root, ArchiveSpec a)
        {
            foreach (var f in a.files ?? new List<FileSpec>())
            {
                var p = f.path.Replace('\\', '/');
                var dir = EnsureDir(root, Path.GetDirectoryName(p) ?? "");
                byte[] data;
                if (f.ytd != null)
                {
                    var list = new List<Texture>();
                    foreach (var t in f.ytd)
                    {
                        var tex = DDSIO.GetTexture(File.ReadAllBytes(t.dds));
                        tex.Name = t.name.ToLowerInvariant();
                        tex.NameHash = JenkHash.GenHash(tex.Name);
                        list.Add(tex);
                    }
                    var td = new TextureDictionary();
                    td.BuildFromTextureList(list);
                    data = new YtdFile { TextureDict = td }.Save();
                }
                else if (f.text != null) data = Encoding.UTF8.GetBytes(f.text);
                else if (f.bin != null) data = File.ReadAllBytes(f.bin);
                else throw new ToolException($"Fichier de test sans contenu : {f.path}");
                RpfFile.CreateFile(dir, Path.GetFileName(p), data);
            }
            foreach (var sub in a.archives ?? new List<ArchiveSpec>())
            {
                var p = sub.path.Replace('\\', '/');
                var dir = EnsureDir(root, Path.GetDirectoryName(p) ?? "");
                var child = RpfFile.CreateNew(dir, Path.GetFileName(p), RpfEncryption.OPEN);
                Fill(child.Root, sub);
            }
        }
    }
}
