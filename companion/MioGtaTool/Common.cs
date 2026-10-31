using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.RegularExpressions;
using CodeWalker.GameFiles;

namespace MioGtaTool
{
    /// <summary>Erreur "attendue" : message lisible, pas de pile d'appels.</summary>
    public class ToolException : Exception
    {
        public int ExitCode { get; }
        public ToolException(string message, int exitCode = 2) : base(message) { ExitCode = exitCode; }
    }

    /// <summary>
    /// Sortie machine : une ligne JSON par evenement sur stdout.
    /// L'addon Blender lit ces lignes dans un thread separe (aucun appel bpy depuis ce thread).
    /// </summary>
    public static class Out
    {
        private static readonly object Lock = new object();
        public static readonly JsonSerializerOptions Json = new JsonSerializerOptions
        {
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            WriteIndented = false,
        };

        public static void Emit(object o)
        {
            var line = JsonSerializer.Serialize(o, Json);
            lock (Lock)
            {
                Console.Out.WriteLine(line);
                Console.Out.Flush();
            }
        }

        public static void Progress(long done, long total, string message)
            => Emit(new { type = "progress", done, total, message });

        public static void Log(string level, string message)
            => Emit(new { type = "log", level, message });

        public static void Result(object data)
            => Emit(new { type = "result", ok = true, data });

        public static void Fail(string error)
            => Emit(new { type = "result", ok = false, error });
    }

    public class Args
    {
        private readonly Dictionary<string, List<string>> _values = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> _flags = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        public string Command { get; }

        public Args(string[] argv)
        {
            Command = argv.Length > 0 ? argv[0].ToLowerInvariant() : "help";
            for (int i = 1; i < argv.Length; i++)
            {
                var a = argv[i];
                if (!a.StartsWith("--")) throw new ToolException($"Argument inattendu : {a}");
                var key = a.Substring(2);
                if (i + 1 < argv.Length && !argv[i + 1].StartsWith("--"))
                {
                    if (!_values.TryGetValue(key, out var list)) _values[key] = list = new List<string>();
                    list.Add(argv[++i]);
                }
                else
                {
                    _flags.Add(key);
                }
            }
        }

        public bool Flag(string key) => _flags.Contains(key);
        public string Get(string key, string def = null) => _values.TryGetValue(key, out var l) ? l[l.Count - 1] : def;
        public List<string> GetAll(string key) => _values.TryGetValue(key, out var l) ? l : new List<string>();
        public string Require(string key)
        {
            var v = Get(key);
            if (string.IsNullOrEmpty(v)) throw new ToolException($"Option obligatoire manquante : --{key}");
            return v;
        }
    }

    public static class Util
    {
        public static string NormPath(string p) => (p ?? "").Replace('\\', '/').Trim('/').ToLowerInvariant();

        public static string Hash16(byte[] data)
        {
            if (data == null) return "";
            using (var sha = SHA1.Create())
            {
                var h = sha.ComputeHash(data);
                var sb = new StringBuilder(16);
                for (int i = 0; i < 8; i++) sb.Append(h[i].ToString("x2", CultureInfo.InvariantCulture));
                return sb.ToString();
            }
        }

        public static float[] V3(SharpDX.Vector3 v) => new[] { v.X, v.Y, v.Z };
        public static float[] V4(SharpDX.Vector4 v) => new[] { v.X, v.Y, v.Z, v.W };

        public static void WriteAtomic(string path, byte[] data)
        {
            var dir = Path.GetDirectoryName(Path.GetFullPath(path));
            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
            var tmp = path + ".tmp";
            File.WriteAllBytes(tmp, data);
            if (File.Exists(path)) File.Delete(path);
            File.Move(tmp, path);
        }

        public static void CheckCancel(string cancelFile)
        {
            if (!string.IsNullOrEmpty(cancelFile) && File.Exists(cancelFile))
                throw new ToolException("Operation annulee par l'utilisateur.", 3);
        }

        /// <summary>Charge une ressource binaire "libre" (fichier sur disque, en-tete RSC7).</summary>
        public static T LoadLooseResource<T>(string path) where T : class, PackedFile, new()
        {
            var data = File.ReadAllBytes(path);
            if (data.Length < 16 || BitConverter.ToUInt32(data, 0) != 0x37435352)
                throw new ToolException($"{Path.GetFileName(path)} n'est pas une ressource binaire RSC7 (XML renomme ou fichier corrompu ?).");
            var file = new T();
            RpfFile.LoadResourceFile(file, data, 0);
            return file;
        }
    }

    /// <summary>Initialisation de l'acces aux archives du jeu (cles + generation).</summary>
    public static class Game
    {
        public static void Init(Args args)
        {
            bool gen9 = args.Flag("gen9");
            RpfManager.IsGen9 = gen9;
            if (args.Flag("no-keys"))
            {
                // Mode developpement/tests : seules les archives non chiffrees (OPEN/NONE) sont lisibles.
                return;
            }
            var gta = args.Require("gta");
            var exe = gen9 ? "GTA5_Enhanced.exe" : "GTA5.exe";
            if (!File.Exists(Path.Combine(gta, exe)) && !File.Exists(Path.Combine(gta, exe.ToLowerInvariant())))
                throw new ToolException($"{exe} introuvable dans « {gta} ». Verifie le chemin GTA V et la generation (Legacy = GTA5.exe, Enhanced = GTA5_Enhanced.exe).");
            try
            {
                // CodeWalker concatene le dossier et "\\gta5.exe" : chemin Windows attendu.
                GTA5Keys.LoadFromPath(gta.TrimEnd('\\', '/'), gen9, null);
            }
            catch (Exception ex)
            {
                throw new ToolException($"Impossible d'extraire les cles de dechiffrement depuis {exe} : {ex.Message}");
            }
        }
    }

    /// <summary>
    /// Priorite de chargement d'un chemin du jeu (plus grand = remplace les plus petits).
    /// Logique alignee sur Sollumz (shared/game_assets/game_files.py) : base &lt; update.rpf &lt; DLC par ordre dlclist
    /// (dlcpacks = 2*i, dlc_patch = 2*i+1), mods en dernier si inclus.
    /// </summary>
    public static class Priority
    {
        private static readonly Regex DlcPack = new Regex(@"^(?:update/)?x64/dlcpacks/([^/]+)/dlc[0-9]?\.rpf", RegexOptions.Compiled);
        private static readonly Regex DlcPatch = new Regex(@"^update/update[0-9]*\.rpf/dlc_patch/([^/]+)/", RegexOptions.Compiled);

        public static int Of(string normPath, Dictionary<string, int> dlcOrder)
        {
            if (normPath.StartsWith("mods/")) return 1_000_000 + Of(normPath.Substring(5), dlcOrder);
            var m = DlcPack.Match(normPath);
            if (m.Success) return 10 + 2 * DlcIndex(m.Groups[1].Value, dlcOrder);
            m = DlcPatch.Match(normPath);
            if (m.Success) return 10 + 2 * DlcIndex(m.Groups[1].Value, dlcOrder) + 1;
            if (normPath.StartsWith("update/")) return 1;
            return 0;
        }

        private static int DlcIndex(string name, Dictionary<string, int> dlcOrder)
        {
            if (dlcOrder != null && dlcOrder.TryGetValue(name.ToLowerInvariant(), out var i)) return i;
            return 5000; // DLC absent de dlclist.xml : non charge par le jeu, mais garde une priorite haute et signalee.
        }

        public static Dictionary<string, int> ParseDlcList(string xml)
        {
            var result = new Dictionary<string, int>();
            var doc = new System.Xml.XmlDocument();
            doc.LoadXml(xml);
            var items = doc.SelectNodes("//Paths/Item");
            int idx = 0;
            foreach (System.Xml.XmlNode item in items)
            {
                var t = (item.InnerText ?? "").Trim().ToLowerInvariant();
                if (t.StartsWith("platform:/dlcpacks/")) t = t.Substring("platform:/dlcpacks/".Length);
                else if (t.StartsWith("dlcpacks:/")) t = t.Substring("dlcpacks:/".Length);
                t = t.Trim('/');
                if (t.Length > 0 && !result.ContainsKey(t)) result[t] = idx;
                idx++;
            }
            return result;
        }
    }

    /// <summary>Ensemble d'archives RPF ouvertes (racines + archives imbriquees).</summary>
    public class RpfSet
    {
        public readonly List<RpfFile> All = new List<RpfFile>();
        public readonly Dictionary<string, RpfFileEntry> Entries = new Dictionary<string, RpfFileEntry>();
        public readonly List<string> Errors = new List<string>();

        public static IEnumerable<string> FindRootRpfs(string gta, bool includeMods)
        {
            var root = Path.GetFullPath(gta);
            foreach (var f in Directory.EnumerateFiles(root, "*.rpf", SearchOption.AllDirectories))
            {
                // Filtre explicite : sous Windows le motif "*.rpf" accepte aussi des extensions plus longues.
                if (!f.EndsWith(".rpf", StringComparison.OrdinalIgnoreCase)) continue;
                var rel = Util.NormPath(Path.GetRelativePath(root, f));
                if (!includeMods && rel.StartsWith("mods/")) continue;
                yield return f;
            }
        }

        public void OpenRoot(string gta, string fullPath)
        {
            var rel = Path.GetRelativePath(Path.GetFullPath(gta), fullPath).Replace('/', '\\');
            var rf = new RpfFile(fullPath, rel);
            rf.ScanStructure(null, e => Errors.Add(e));
            if (rf.LastException != null) return;
            Add(rf);
        }

        private void Add(RpfFile rf)
        {
            All.Add(rf);
            if (rf.AllEntries != null)
            {
                foreach (var e in rf.AllEntries)
                {
                    if (e is RpfFileEntry fe) Entries[Util.NormPath(fe.Path)] = fe;
                }
            }
            if (rf.Children != null)
                foreach (var c in rf.Children) Add(c);
        }

        public byte[] Extract(RpfFileEntry e) => e.File.ExtractFile(e);

        public T Load<T>(RpfFileEntry e) where T : class, PackedFile, new()
        {
            var data = Extract(e);
            if (data == null) return null;
            var f = new T();
            f.Load(data, e);
            return f;
        }
    }
}
