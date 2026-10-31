using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CodeWalker.GameFiles;

namespace MioGtaTool
{
    /// <summary>
    /// index : parcourt les archives RPF de l'installation GTA V (sans jamais les modifier) et ecrit un index JSONL :
    ///   - toutes les textures des dictionnaires .ytd (nom, dictionnaire, chemin, format, dimensions, mips, empreinte des donnees) ;
    ///   - optionnellement (--embedded) les textures integrees aux .ydr/.ydd/.yft ;
    ///   - les archetypes des .ytyp (nom -> dictionnaire de textures), pour retrouver la provenance d'un modele ;
    ///   - les relations de dictionnaires parents (gtxd.meta / gtxd.ymt) ;
    ///   - l'ordre de chargement des DLC (dlclist.xml) pour la priorite des versions.
    /// Le fichier est ecrit dans un .tmp puis renomme : une annulation ne laisse jamais d'index partiel.
    /// </summary>
    public static class IndexCommand
    {
        private static readonly HashSet<string> GtxdNames = new HashSet<string> { "gtxd.ymt", "gtxd.meta", "mph4_gtxd.ymt" };

        public static string ComputeSignature(string gta, bool includeMods, bool gen9)
        {
            // Doit rester identique a textures/index.py::compute_signature (cote addon).
            var root = Path.GetFullPath(gta);
            var lines = new List<string>();
            foreach (var f in RpfSet.FindRootRpfs(root, includeMods))
            {
                var fi = new FileInfo(f);
                lines.Add($"{Util.NormPath(Path.GetRelativePath(root, f))}|{fi.Length}|{new DateTimeOffset(fi.LastWriteTimeUtc).ToUnixTimeSeconds()}");
            }
            var exe = Path.Combine(root, gen9 ? "GTA5_Enhanced.exe" : "GTA5.exe");
            if (File.Exists(exe))
            {
                var fi = new FileInfo(exe);
                lines.Add($"{(gen9 ? "gta5_enhanced.exe" : "gta5.exe")}|{fi.Length}|{new DateTimeOffset(fi.LastWriteTimeUtc).ToUnixTimeSeconds()}");
            }
            lines.Sort(StringComparer.Ordinal);
            using (var sha = SHA1.Create())
            {
                var h = sha.ComputeHash(Encoding.UTF8.GetBytes(string.Join("\n", lines)));
                return BitConverter.ToString(h, 0, 8).Replace("-", "").ToLowerInvariant();
            }
        }

        public static int Run(Args args)
        {
            var gta = args.Require("gta");
            var outPath = args.Require("out");
            bool includeMods = args.Flag("include-mods");
            bool embedded = args.Flag("embedded");
            bool gen9 = args.Flag("gen9");
            var cancel = args.Get("cancel-file");
            if (!Directory.Exists(gta)) throw new ToolException($"Dossier GTA V introuvable : {gta}");

            Game.Init(args);
            var sw = Stopwatch.StartNew();

            var roots = RpfSet.FindRootRpfs(gta, includeMods).ToList();
            if (roots.Count == 0) throw new ToolException($"Aucune archive .rpf trouvee dans « {gta} ».");

            var set = new RpfSet();
            for (int i = 0; i < roots.Count; i++)
            {
                Util.CheckCancel(cancel);
                Out.Progress(i, roots.Count, "Structure : " + Path.GetFileName(roots[i]));
                set.OpenRoot(gta, roots[i]);
            }
            foreach (var e in set.Errors.Take(50)) Out.Log("warning", "Archive illisible : " + e.Split('\n')[0]);
            if (set.All.Count == 0)
                throw new ToolException("Aucune archive n'a pu etre lue (cles de dechiffrement invalides ou mauvaise generation Legacy/Enhanced ?).");

            // Noms de fichiers -> index Jenkins, pour resoudre les hash des archetypes/dictionnaires.
            foreach (var key in set.Entries.Keys)
            {
                var name = Path.GetFileNameWithoutExtension(key);
                JenkIndex.Ensure(name);
            }

            Dictionary<string, int> dlcOrder = null;
            if (set.Entries.TryGetValue("update/update.rpf/common/data/dlclist.xml", out var dlcEntry))
            {
                try
                {
                    var bytes = set.Extract(dlcEntry);
                    using (var r = new StreamReader(new MemoryStream(bytes), Encoding.UTF8, true))
                        dlcOrder = Priority.ParseDlcList(r.ReadToEnd());
                }
                catch (Exception ex) { Out.Log("warning", "dlclist.xml illisible : " + ex.Message); }
            }
            else
            {
                Out.Log("warning", "dlclist.xml introuvable : l'ordre des DLC sera approximatif.");
            }

            var work = new List<KeyValuePair<string, RpfFileEntry>>();
            foreach (var kv in set.Entries)
            {
                var n = Path.GetFileName(kv.Key);
                var ext = Path.GetExtension(n);
                if (ext == ".ytd" || ext == ".ytyp" || GtxdNames.Contains(n) || (embedded && (ext == ".ydr" || ext == ".ydd" || ext == ".yft")))
                    work.Add(kv);
            }
            work.Sort((a, b) => string.CompareOrdinal(a.Key, b.Key));

            var tmp = outPath + ".tmp";
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPath)));
            long nTex = 0, nArch = 0, nGtxd = 0, nErr = 0;
            using (var w = new StreamWriter(tmp, false, new UTF8Encoding(false)))
            {
                void Write(object o) => w.WriteLine(JsonSerializer.Serialize(o, Out.Json));

                Write(new
                {
                    k = "meta",
                    tool = Program.Version,
                    codewalker = Program.CodeWalkerCommit,
                    gta = Path.GetFullPath(gta),
                    gen9,
                    include_mods = includeMods,
                    embedded,
                    signature = ComputeSignature(gta, includeMods, gen9),
                    created = DateTime.UtcNow.ToString("o"),
                    rpf_roots = roots.Count,
                    rpf_total = set.All.Count,
                });
                if (dlcOrder != null)
                    foreach (var kv in dlcOrder) Write(new { k = "dlc", n = kv.Key, i = kv.Value });

                var lastReport = Stopwatch.StartNew();
                for (int i = 0; i < work.Count; i++)
                {
                    if ((i & 31) == 0) Util.CheckCancel(cancel);
                    var path = work[i].Key;
                    var entry = work[i].Value;
                    if (lastReport.ElapsedMilliseconds > 500)
                    {
                        Out.Progress(i, work.Count, "Index : " + Path.GetFileName(path));
                        lastReport.Restart();
                    }
                    var pr = Priority.Of(path, dlcOrder);
                    var fname = Path.GetFileName(path);
                    var ext = Path.GetExtension(fname);
                    var stem = Path.GetFileNameWithoutExtension(fname);
                    try
                    {
                        if (ext == ".ytd")
                        {
                            var ytd = set.Load<YtdFile>(entry);
                            nTex += WriteTextures(Write, ytd?.TextureDict, stem, path, "ytd", pr);
                        }
                        else if (ext == ".ytyp")
                        {
                            var ytyp = set.Load<YtypFile>(entry);
                            if (ytyp?.AllArchetypes != null)
                            {
                                foreach (var a in ytyp.AllArchetypes)
                                {
                                    if (a == null) continue;
                                    var d = a._BaseArchetypeDef;
                                    Write(new
                                    {
                                        k = "arch",
                                        n = JenkIndex.TryGetString(d.name),
                                        nh = (uint)d.name,
                                        t = JenkIndex.TryGetString(d.textureDictionary),
                                        th = (uint)d.textureDictionary,
                                        a = JenkIndex.TryGetString(d.assetName),
                                        ah = (uint)d.assetName,
                                        y = path,
                                        pr,
                                    });
                                    nArch++;
                                }
                            }
                        }
                        else if (GtxdNames.Contains(fname))
                        {
                            var g = set.Load<GtxdFile>(entry);
                            if (g?.TxdRelationships != null)
                            {
                                foreach (var kv in g.TxdRelationships)
                                {
                                    Write(new { k = "gtxd", c = kv.Key.ToLowerInvariant(), p = kv.Value.ToLowerInvariant(), y = path, pr });
                                    nGtxd++;
                                }
                            }
                        }
                        else if (ext == ".ydr")
                        {
                            var ydr = set.Load<YdrFile>(entry);
                            nTex += WriteTextures(Write, ydr?.Drawable?.ShaderGroup?.TextureDictionary, stem, path, "ydr", pr);
                        }
                        else if (ext == ".ydd")
                        {
                            var ydd = set.Load<YddFile>(entry);
                            if (ydd?.Drawables != null)
                                foreach (var dr in ydd.Drawables)
                                    nTex += WriteTextures(Write, dr?.ShaderGroup?.TextureDictionary, stem, path, "ydd", pr);
                        }
                        else if (ext == ".yft")
                        {
                            var yft = set.Load<YftFile>(entry);
                            nTex += WriteTextures(Write, yft?.Fragment?.Drawable?.ShaderGroup?.TextureDictionary, stem, path, "yft", pr);
                        }
                    }
                    catch (ToolException) { throw; }
                    catch (Exception ex)
                    {
                        nErr++;
                        Write(new { k = "err", p = path, m = ex.Message });
                    }
                }
                Write(new { k = "end", textures = nTex, archetypes = nArch, gtxd = nGtxd, errors = nErr, seconds = sw.Elapsed.TotalSeconds });
            }
            if (File.Exists(outPath)) File.Delete(outPath);
            File.Move(tmp, outPath);
            Out.Progress(work.Count, work.Count, "Index termine");
            Out.Result(new { index = Path.GetFullPath(outPath), textures = nTex, archetypes = nArch, gtxd = nGtxd, errors = nErr, files = work.Count, seconds = sw.Elapsed.TotalSeconds });
            return 0;
        }

        private static long WriteTextures(Action<object> write, TextureDictionary td, string dict, string path, string source, int pr)
        {
            var texs = td?.Textures?.data_items;
            if (texs == null) return 0;
            long n = 0;
            foreach (var t in texs)
            {
                if (t == null || string.IsNullOrEmpty(t.Name)) continue;
                write(new
                {
                    k = "tex",
                    n = t.Name.ToLowerInvariant(),
                    d = dict,
                    p = path,
                    s = source,
                    w = (int)t.Width,
                    h = (int)t.Height,
                    f = t.Format.ToString(),
                    m = (int)t.Levels,
                    u = t.Usage.ToString(),
                    x = Util.Hash16(t.Data?.FullData),
                    pr,
                });
                n++;
            }
            return n;
        }
    }
}
