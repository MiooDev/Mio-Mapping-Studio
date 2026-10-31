using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using CodeWalker.GameFiles;
using CodeWalker.Utils;

namespace MioGtaTool
{
    /// <summary>
    /// extract : extrait des textures precises (nom + fichier source) en DDS, sans recompression.
    /// Le DDS est produit par DDSIO.GetDDSFile : les donnees de pixels (format, mips, alpha) sont recopiees telles quelles.
    /// Un fichier .json voisin conserve les metadonnees d'origine (usage, flags) pour reconstruire le YTD a l'identique.
    ///
    /// --requests : JSON [{"name": "...", "path": "x64i.rpf/.../dict.ytd", "out": "chemin/relatif.dds"}]
    /// </summary>
    public static class ExtractCommand
    {
        public class Request
        {
            public string name { get; set; }
            public string path { get; set; }
            public string @out { get; set; }
        }

        public static int Run(Args args)
        {
            var gta = args.Require("gta");
            var reqPath = args.Require("requests");
            var outDir = args.Require("out");
            var cancel = args.Get("cancel-file");
            Game.Init(args);

            var requests = JsonSerializer.Deserialize<List<Request>>(File.ReadAllText(reqPath)) ?? new List<Request>();
            if (requests.Count == 0) { Out.Result(new { extracted = 0, items = new object[0] }); return 0; }
            Directory.CreateDirectory(outDir);

            // On n'ouvre que les archives racines necessaires.
            var gtaFull = Path.GetFullPath(gta);
            var neededRoots = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var r in requests)
            {
                var p = Util.NormPath(r.path);
                var idx = p.IndexOf(".rpf/", StringComparison.Ordinal);
                if (idx < 0) throw new ToolException($"Chemin source invalide (pas dans une archive RPF) : {r.path}");
                neededRoots.Add(p.Substring(0, idx + 4));
            }
            var set = new RpfSet();
            int ri = 0;
            foreach (var root in neededRoots)
            {
                Util.CheckCancel(cancel);
                Out.Progress(ri++, neededRoots.Count + requests.Count, "Ouverture : " + root);
                var full = Path.Combine(gtaFull, root.Replace('/', Path.DirectorySeparatorChar));
                if (!File.Exists(full))
                {
                    // Recherche insensible a la casse (Windows ne la distingue pas, Linux si).
                    full = RpfSet.FindRootRpfs(gtaFull, true).FirstOrDefault(f => Util.NormPath(Path.GetRelativePath(gtaFull, f)) == root);
                    if (full == null) throw new ToolException($"Archive introuvable : {root}");
                }
                set.OpenRoot(gtaFull, full);
            }

            var cache = new Dictionary<string, Dictionary<string, Texture>>();
            var results = new List<object>();
            int ok = 0, done = 0;
            foreach (var r in requests)
            {
                Util.CheckCancel(cancel);
                Out.Progress(neededRoots.Count + done++, neededRoots.Count + requests.Count, "Extraction : " + r.name);
                var p = Util.NormPath(r.path);
                try
                {
                    if (!cache.TryGetValue(p, out var texs))
                    {
                        if (!set.Entries.TryGetValue(p, out var entry)) throw new Exception("fichier introuvable dans les archives");
                        texs = LoadTextures(set, entry, p);
                        cache[p] = texs;
                    }
                    if (!texs.TryGetValue(r.name.ToLowerInvariant(), out var tex)) throw new Exception("texture absente de ce fichier");
                    var dds = DDSIO.GetDDSFile(tex);
                    var outFile = Path.GetFullPath(Path.Combine(outDir, r.@out));
                    if (!outFile.StartsWith(Path.GetFullPath(outDir), StringComparison.Ordinal)) throw new Exception("chemin de sortie invalide");
                    Util.WriteAtomic(outFile, dds);
                    var meta = new
                    {
                        name = tex.Name?.ToLowerInvariant(),
                        source = p,
                        width = (int)tex.Width,
                        height = (int)tex.Height,
                        format = tex.Format.ToString(),
                        mips = (int)tex.Levels,
                        usage = tex.Usage.ToString(),
                        usage_flags = tex.UsageFlags.ToString(),
                        extra_flags = tex.ExtraFlags,
                        unk32 = (int)tex.Unknown_32h,
                        hash = Util.Hash16(tex.Data?.FullData),
                        dds_size = dds.Length,
                    };
                    File.WriteAllText(Path.ChangeExtension(outFile, ".json"), JsonSerializer.Serialize(meta, Out.Json));
                    results.Add(new { r.name, r.path, file = outFile, ok = true, meta });
                    ok++;
                }
                catch (Exception ex)
                {
                    results.Add(new { r.name, r.path, ok = false, error = ex.Message });
                }
            }
            Out.Result(new { extracted = ok, failed = requests.Count - ok, items = results });
            return ok == requests.Count ? 0 : 1;
        }

        private static Dictionary<string, Texture> LoadTextures(RpfSet set, RpfFileEntry entry, string path)
        {
            var dict = new Dictionary<string, Texture>();
            void AddAll(TextureDictionary td)
            {
                var items = td?.Textures?.data_items;
                if (items == null) return;
                foreach (var t in items)
                    if (t != null && !string.IsNullOrEmpty(t.Name) && !dict.ContainsKey(t.Name.ToLowerInvariant()))
                        dict[t.Name.ToLowerInvariant()] = t;
            }
            switch (Path.GetExtension(path))
            {
                case ".ytd": AddAll(set.Load<YtdFile>(entry)?.TextureDict); break;
                case ".ydr": AddAll(set.Load<YdrFile>(entry)?.Drawable?.ShaderGroup?.TextureDictionary); break;
                case ".ydd":
                    var ydd = set.Load<YddFile>(entry);
                    if (ydd?.Drawables != null) foreach (var d in ydd.Drawables) AddAll(d?.ShaderGroup?.TextureDictionary);
                    break;
                case ".yft": AddAll(set.Load<YftFile>(entry)?.Fragment?.Drawable?.ShaderGroup?.TextureDictionary); break;
                default: throw new Exception("type de fichier non pris en charge pour l'extraction");
            }
            return dict;
        }
    }
}
