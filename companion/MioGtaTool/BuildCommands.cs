using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Xml;
using CodeWalker.GameFiles;
using CodeWalker.Utils;

namespace MioGtaTool
{
    /// <summary>
    /// build-ytd : construit un dictionnaire de textures binaire (.ytd, ressource RSC7) a partir de fichiers DDS.
    /// Les pixels DDS sont recopies sans recompression (DDSIO.GetTexture). Le fichier produit est relu pour verification.
    /// --manifest : {"name": "mio_garage", "textures": [{"name": "tex", "dds": "C:/.../tex.dds", "meta": "C:/.../tex.json"}]}
    /// </summary>
    public static class BuildYtdCommand
    {
        public class Item { public string name { get; set; } public string dds { get; set; } public string meta { get; set; } }
        public class Manifest { public string name { get; set; } public List<Item> textures { get; set; } }

        public static int Run(Args args)
        {
            var manifestPath = args.Require("manifest");
            var outPath = args.Require("out");
            bool gen9 = args.Flag("gen9");
            RpfManager.IsGen9 = gen9;

            var m = JsonSerializer.Deserialize<Manifest>(File.ReadAllText(manifestPath));
            if (m?.textures == null || m.textures.Count == 0) throw new ToolException("Manifeste vide : aucune texture a mettre dans le YTD.");

            var seen = new HashSet<string>();
            var list = new List<Texture>();
            var expected = new Dictionary<string, (int w, int h, string f, int mips, string hash)>();
            var warnings = new List<string>();
            foreach (var it in m.textures)
            {
                var name = (it.name ?? "").ToLowerInvariant();
                if (string.IsNullOrEmpty(name)) throw new ToolException("Texture sans nom dans le manifeste.");
                if (!seen.Add(name)) throw new ToolException($"Texture en double dans le manifeste : {name}");
                if (!File.Exists(it.dds)) throw new ToolException($"DDS introuvable : {it.dds}");
                var bytes = File.ReadAllBytes(it.dds);
                if (bytes.Length < 4 || bytes[0] != 'D' || bytes[1] != 'D' || bytes[2] != 'S' || bytes[3] != ' ')
                    throw new ToolException($"{Path.GetFileName(it.dds)} n'est pas un fichier DDS.");
                Texture tex;
                try { tex = DDSIO.GetTexture(bytes); }
                catch (Exception ex) { throw new ToolException($"Format DDS non pris en charge pour {name} : {ex.Message}"); }
                if (tex == null) throw new ToolException($"Format DDS non pris en charge pour {name}.");
                tex.Name = name;
                tex.NameHash = JenkHash.GenHash(name);
                JenkIndex.Ensure(name);
                if (!string.IsNullOrEmpty(it.meta) && File.Exists(it.meta))
                    ApplyMeta(tex, it.meta);
                list.Add(tex);
                var full = tex.Data?.FullData ?? new byte[0];
                var stored = full;
                if (!gen9)
                {
                    // Format RAGE Legacy : taille d'un mip = taille du precedent / 4 (comme le jeu et CodeWalker).
                    // Les niveaux plus petits que 4x4 d'un DDS BCn standard sont donc tronques : on le signale.
                    long len = 0, l = (long)tex.Stride * tex.Height;
                    for (int i = 0; i < tex.Levels; i++) { len += l; l /= 4; }
                    if (len < full.Length)
                    {
                        warnings.Add($"{name} : {full.Length - len} octets de mips < 4x4 non stockes (format RAGE)");
                        stored = full.Take((int)len).ToArray();
                    }
                    else if (len > full.Length)
                        throw new ToolException($"{name} : donnees DDS incompletes ({full.Length} octets, {len} attendus).");
                }
                expected[name] = (tex.Width, tex.Height, tex.Format.ToString(), tex.Levels, Util.Hash16(stored));
            }

            var td = new TextureDictionary();
            td.BuildFromTextureList(list);
            var ytd = new YtdFile { TextureDict = td };
            var data = ytd.Save();
            Util.WriteAtomic(outPath, data);

            // Relecture du fichier ecrit avec le lecteur CodeWalker.Core.
            var check = Util.LoadLooseResource<YtdFile>(outPath);
            var problems = new List<string>();
            var got = check.TextureDict?.Textures?.data_items ?? new Texture[0];
            if (got.Length != expected.Count) problems.Add($"{got.Length} textures relues au lieu de {expected.Count}");
            foreach (var t in got)
            {
                var n = t.Name?.ToLowerInvariant() ?? "";
                if (!expected.TryGetValue(n, out var e)) { problems.Add($"texture inattendue {n}"); continue; }
                if (t.Width != e.w || t.Height != e.h) problems.Add($"{n} : dimensions modifiees");
                if (t.Format.ToString() != e.f) problems.Add($"{n} : format modifie");
                if (t.Levels != e.mips) problems.Add($"{n} : nombre de mips modifie");
                if (Util.Hash16(t.Data?.FullData) != e.hash) problems.Add($"{n} : donnees de pixels modifiees");
            }
            if (problems.Count > 0) throw new ToolException("YTD ecrit mais la relecture a echoue : " + string.Join("; ", problems));

            Out.Result(new
            {
                file = Path.GetFullPath(outPath),
                size = new FileInfo(outPath).Length,
                gen9,
                textures = got.Select(t => new { name = t.Name, width = (int)t.Width, height = (int)t.Height, format = t.Format.ToString(), mips = (int)t.Levels }).ToArray(),
                verified = true,
                warnings,
            });
            return 0;
        }

        private static void ApplyMeta(Texture tex, string metaPath)
        {
            using (var doc = JsonDocument.Parse(File.ReadAllText(metaPath)))
            {
                var r = doc.RootElement;
                if (r.TryGetProperty("usage", out var u) && Enum.TryParse<TextureUsage>(u.GetString(), out var usage)) tex.Usage = usage;
                if (r.TryGetProperty("usage_flags", out var uf) && Enum.TryParse<TextureUsageFlags>(uf.GetString(), out var flags)) tex.UsageFlags = flags;
                if (r.TryGetProperty("extra_flags", out var ef) && ef.TryGetUInt32(out var extra)) tex.ExtraFlags = extra;
                if (r.TryGetProperty("unk32", out var u32) && u32.TryGetInt32(out var v32)) tex.Unknown_32h = (ushort)v32;
            }
        }
    }

    /// <summary>
    /// xml2bin : compile un fichier CodeWalker XML (.ydr.xml, .ybn.xml, .ytd.xml, .ytyp.xml, .ymap.xml) en ressource
    /// binaire avec les importeurs de CodeWalker.Core (XmlMeta.GetData), comme le fait l'interface de CodeWalker.
    /// Les textures integrees sont cherchees dans le dossier voisin portant le nom de l'asset (convention Sollumz/CodeWalker).
    /// </summary>
    public static class Xml2BinCommand
    {
        public static int Run(Args args)
        {
            var input = args.Require("in");
            bool gen9 = args.Flag("gen9");
            RpfManager.IsGen9 = gen9;
            if (!File.Exists(input)) throw new ToolException($"Fichier introuvable : {input}");
            var fname = Path.GetFileName(input);
            var fnamel = fname.ToLowerInvariant();
            var mformat = XmlMeta.GetXMLFormat(fnamel, out int trimlength);
            if (mformat == MetaFormat.XML) throw new ToolException($"{fname} : extension non reconnue (attendu .ydr.xml, .ytyp.xml...).");
            var outName = fname.Substring(0, fname.Length - trimlength);
            var output = args.Get("out") ?? Path.Combine(Path.GetDirectoryName(Path.GetFullPath(input)), outName);
            var fpathin = Path.GetFullPath(input);
            fpathin = fpathin.Substring(0, fpathin.Length - trimlength);
            fpathin = Path.Combine(Path.GetDirectoryName(fpathin), Path.GetFileNameWithoutExtension(fpathin));

            var doc = new XmlDocument();
            doc.Load(input);
            byte[] data;
            try { data = XmlMeta.GetData(doc, mformat, fpathin); }
            catch (Exception ex) { throw new ToolException($"Compilation CodeWalker impossible pour {fname} : {ex.Message}"); }
            if (data == null || data.Length == 0) throw new ToolException($"Compilation CodeWalker impossible pour {fname} (schema non pris en charge ou contenu vide).");
            Util.WriteAtomic(output, data);
            Out.Result(new { input = Path.GetFullPath(input), output = Path.GetFullPath(output), format = mformat.ToString(), size = data.Length, gen9 });
            return 0;
        }
    }

    /// <summary>
    /// make-ymap : genere un YMAP binaire de placement a partir d'un YTYP binaire deja exporte.
    /// --spec {"name":"mio_garage","entities":[{"archetype":"mio_garage","position":[x,y,z],"rotation":[x,y,z,w],
    ///          "flags":32,"lod_dist":-1,"mlo":false}]}
    /// Les extents sont calcules par CodeWalker (CalcExtents) a partir des archetypes du YTYP.
    /// </summary>
    public static class MakeYmapCommand
    {
        public class Ent
        {
            public string archetype { get; set; }
            public float[] position { get; set; }
            public float[] rotation { get; set; }
            public uint flags { get; set; }
            public float lod_dist { get; set; } = -1;
            public bool mlo { get; set; }
        }
        public class Spec { public string name { get; set; } public List<Ent> entities { get; set; } }

        public static int Run(Args args)
        {
            var spec = JsonSerializer.Deserialize<Spec>(File.ReadAllText(args.Require("spec")));
            var ytypPath = args.Require("ytyp");
            var outPath = args.Require("out");
            RpfManager.IsGen9 = args.Flag("gen9");
            if (spec?.entities == null || spec.entities.Count == 0) throw new ToolException("Aucune entite a placer.");

            var ytyp = Util.LoadLooseResource<YtypFile>(ytypPath);
            var archs = new Dictionary<uint, Archetype>();
            foreach (var a in ytyp.AllArchetypes ?? new Archetype[0]) archs[(uint)a._BaseArchetypeDef.name] = a;

            var ymap = new YmapFile();
            ymap.Name = spec.name;
            var md = ymap._CMapData;
            md.name = JenkHash.GenHash(spec.name.ToLowerInvariant());
            ymap._CMapData = md;
            JenkIndex.Ensure(spec.name.ToLowerInvariant());

            var rnd = new Random((int)JenkHash.GenHash(spec.name));
            foreach (var e in spec.entities)
            {
                var hash = JenkHash.GenHash(e.archetype.ToLowerInvariant());
                JenkIndex.Ensure(e.archetype.ToLowerInvariant());
                if (!archs.TryGetValue(hash, out var arch)) throw new ToolException($"Archetype {e.archetype} absent de {Path.GetFileName(ytypPath)}.");
                var cdef = new CEntityDef
                {
                    archetypeName = hash,
                    flags = e.flags,
                    guid = (uint)rnd.Next(1, int.MaxValue),
                    position = new SharpDX.Vector3(e.position[0], e.position[1], e.position[2]),
                    rotation = e.rotation != null ? new SharpDX.Vector4(e.rotation[0], e.rotation[1], e.rotation[2], e.rotation[3]) : new SharpDX.Vector4(0, 0, 0, 1),
                    scaleXY = 1f,
                    scaleZ = 1f,
                    parentIndex = -1,
                    lodDist = e.lod_dist > 0 ? e.lod_dist : arch.LodDist,
                    childLodDist = 0f,
                    lodLevel = rage__eLodType.LODTYPES_DEPTH_ORPHANHD,
                    numChildren = 0,
                    priorityLevel = rage__ePriorityLevel.PRI_REQUIRED,
                    ambientOcclusionMultiplier = 255,
                    artificialAmbientOcclusion = 255,
                    tintValue = 0,
                };
                YmapEntityDef ent;
                if (e.mlo)
                {
                    if (!(arch is MloArchetype)) throw new ToolException($"{e.archetype} n'est pas un archetype MLO.");
                    var mdef = new CMloInstanceDef { CEntityDef = cdef, groupId = 0, floorId = 0, numExitPortals = 0, MLOInstflags = 0 };
                    ent = new YmapEntityDef(ymap, 0, ref mdef);
                }
                else
                {
                    if (arch is MloArchetype) throw new ToolException($"{e.archetype} est un archetype MLO : utiliser \"mlo\": true.");
                    ent = new YmapEntityDef(ymap, 0, ref cdef);
                }
                ent.SetArchetype(arch);
                ymap.AddEntity(ent);
            }
            ymap.CalcFlags();
            ymap.CalcExtents();
            var data = ymap.Save();
            Util.WriteAtomic(outPath, data);

            var check = Util.LoadLooseResource<YmapFile>(outPath);
            Out.Result(new
            {
                file = Path.GetFullPath(outPath),
                size = data.Length,
                entities = check.AllEntities?.Length ?? 0,
                mlo_instances = check.AllEntities?.Count(x => x.MloInstance != null) ?? 0,
                streaming_extents = new[] { Util.V3(check._CMapData.streamingExtentsMin), Util.V3(check._CMapData.streamingExtentsMax) },
                entities_extents = new[] { Util.V3(check._CMapData.entitiesExtentsMin), Util.V3(check._CMapData.entitiesExtentsMax) },
            });
            return 0;
        }
    }
}
