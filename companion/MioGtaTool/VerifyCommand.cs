using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using CodeWalker.GameFiles;
using SharpDX;

namespace MioGtaTool
{
    /// <summary>
    /// verify : relit des fichiers binaires exportes avec CodeWalker.Core et renvoie leur contenu utile a la validation
    /// (bounds du drawable, modeles par LOD, shaders et textures references, collision integree, archetypes, rooms...).
    /// Un fichier XML renomme en binaire est refuse (pas d'en-tete RSC7).
    /// </summary>
    public static class VerifyCommand
    {
        public static int Run(Args args)
        {
            RpfManager.IsGen9 = args.Flag("gen9");
            var files = args.GetAll("file");
            if (files.Count == 0) throw new ToolException("Aucun fichier a verifier (--file).");
            // Les noms sont haches (joaat) dans les fichiers : on enregistre les noms attendus pour les afficher.
            foreach (var n in (args.Get("names") ?? "").Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries))
                JenkIndex.Ensure(n.Trim().ToLowerInvariant());
            foreach (var f in files)
            {
                var stem = Path.GetFileNameWithoutExtension(f).ToLowerInvariant();
                JenkIndex.Ensure(stem);
                JenkIndex.Ensure(stem + "_col");
                if (stem.EndsWith("_col")) JenkIndex.Ensure(stem.Substring(0, stem.Length - 4));
                JenkIndex.Ensure("limbo");
            }
            var results = new List<object>();
            bool allOk = true;
            foreach (var f in files)
            {
                try
                {
                    results.Add(new { file = Path.GetFullPath(f), ok = true, info = Describe(f) });
                }
                catch (Exception ex)
                {
                    allOk = false;
                    results.Add(new { file = Path.GetFullPath(f), ok = false, error = ex.Message });
                }
            }
            Out.Result(new { files = results, all_ok = allOk });
            return allOk ? 0 : 1;
        }

        private static object Describe(string path)
        {
            switch (Path.GetExtension(path).ToLowerInvariant())
            {
                case ".ydr": return DescribeYdr(Util.LoadLooseResource<YdrFile>(path));
                case ".ytd": return DescribeYtd(Util.LoadLooseResource<YtdFile>(path));
                case ".ybn": return new { type = "ybn", bound = DescribeBound(Util.LoadLooseResource<YbnFile>(path).Bounds, Matrix.Identity) };
                case ".ytyp": return DescribeYtyp(Util.LoadLooseResource<YtypFile>(path));
                case ".ymap": return DescribeYmap(Util.LoadLooseResource<YmapFile>(path));
                default: throw new ToolException("Type de fichier non pris en charge par verify.");
            }
        }

        private static object DescribeYdr(YdrFile ydr)
        {
            var d = ydr.Drawable;
            if (d == null) throw new ToolException("Le YDR ne contient pas de drawable.");
            object Lod(DrawableModel[] models)
            {
                if (models == null) return null;
                return models.Select(m => new
                {
                    geometries = m.Geometries?.Length ?? 0,
                    vertices = m.Geometries?.Sum(g => (long)(g.VertexData?.VertexCount ?? 0)) ?? 0,
                    indices = m.Geometries?.Sum(g => (long)g.IndicesCount) ?? 0,
                    shader_ids = m.Geometries?.Select(g => (int)g.ShaderID).ToArray() ?? new int[0],
                }).ToArray();
            }
            var shaders = new List<object>();
            var refTextures = new SortedSet<string>();
            var sh = d.ShaderGroup?.Shaders?.data_items ?? new ShaderFX[0];
            foreach (var s in sh)
            {
                var texs = new List<object>();
                var pl = s?.ParametersList;
                if (pl?.Parameters != null)
                {
                    for (int i = 0; i < pl.Parameters.Length; i++)
                    {
                        var p = pl.Parameters[i];
                        if (p.DataType != 0) continue;
                        var tb = p.Data as TextureBase;
                        var pname = (pl.Hashes != null && i < pl.Hashes.Length) ? pl.Hashes[i].ToString() : i.ToString();
                        var tname = tb?.Name?.ToLowerInvariant();
                        texs.Add(new { param = pname, texture = tname });
                        if (!string.IsNullOrEmpty(tname)) refTextures.Add(tname);
                    }
                }
                shaders.Add(new { name = s?.Name.ToString(), file = s?.FileName.ToString(), textures = texs });
            }
            var embedded = d.ShaderGroup?.TextureDictionary?.Textures?.data_items?.Select(t => t.Name?.ToLowerInvariant()).ToArray() ?? new string[0];
            return new
            {
                type = "ydr",
                name = d.Name,
                bb_min = Util.V3(d.BoundingBoxMin),
                bb_max = Util.V3(d.BoundingBoxMax),
                bs_center = Util.V3(d.BoundingCenter),
                bs_radius = d.BoundingSphereRadius,
                lod_dist = new[] { d.LodDistHigh, d.LodDistMed, d.LodDistLow, d.LodDistVlow },
                lods = new
                {
                    high = Lod(d.DrawableModels?.High),
                    med = Lod(d.DrawableModels?.Med),
                    low = Lod(d.DrawableModels?.Low),
                    vlow = Lod(d.DrawableModels?.VLow),
                },
                shaders,
                referenced_textures = refTextures.ToArray(),
                embedded_textures = embedded,
                bound = d.Bound != null ? DescribeBound(d.Bound, Matrix.Identity) : null,
            };
        }

        private static object DescribeBound(Bounds b, Matrix parent)
        {
            if (b == null) return null;
            var m = b.Transform * parent;
            // AABB de la geometrie reelle dans le repere de l'asset (drawable ou ybn).
            Vector3 mn = new Vector3(float.MaxValue), mx = new Vector3(float.MinValue);
            long nverts = 0, npolys = 0;
            var mats = new SortedSet<int>();
            var children = new List<object>();
            if (b is BoundComposite bc)
            {
                var items = bc.Children?.data_items ?? new Bounds[0];
                for (int i = 0; i < items.Length; i++)
                {
                    var c = items[i];
                    if (c == null) continue;
                    var flags1 = (bc.ChildrenFlags1 != null && i < bc.ChildrenFlags1.Length) ? (uint)bc.ChildrenFlags1[i].Flags1 : 0u;
                    var flags2 = (bc.ChildrenFlags1 != null && i < bc.ChildrenFlags1.Length) ? (uint)bc.ChildrenFlags1[i].Flags2 : 0u;
                    children.Add(new { index = i, type_flags = flags1, include_flags = flags2, bound = DescribeBound(c, m) });
                }
            }
            bool? boxOk = null;
            if (b is BoundGeometry bg)
            {
                var verts = bg.Vertices ?? new Vector3[0];
                nverts = verts.Length;
                npolys = bg.Polygons?.Length ?? 0;
                Vector3 lmn = new Vector3(float.MaxValue), lmx = new Vector3(float.MinValue);
                foreach (var v in verts)
                {
                    var l = v + bg.CenterGeom;
                    lmn = Vector3.Min(lmn, l); lmx = Vector3.Max(lmx, l);
                    var w = Vector3.TransformCoordinate(l, m);
                    mn = Vector3.Min(mn, w); mx = Vector3.Max(mx, w);
                }
                if (nverts > 0)
                {
                    // La boite de la geometrie (utilisee par le moteur physique) doit contenir ses sommets.
                    var tol = 0.05f + bg.Margin;
                    boxOk = lmn.X >= b.BoxMin.X - tol && lmn.Y >= b.BoxMin.Y - tol && lmn.Z >= b.BoxMin.Z - tol &&
                            lmx.X <= b.BoxMax.X + tol && lmx.Y <= b.BoxMax.Y + tol && lmx.Z <= b.BoxMax.Z + tol;
                }
                if (bg.Materials != null) foreach (var mat in bg.Materials) mats.Add((int)mat.Type.Index);
            }
            else if (!(b is BoundComposite))
            {
                foreach (var c in Corners(b.BoxMin, b.BoxMax))
                {
                    var w = Vector3.TransformCoordinate(c, m);
                    mn = Vector3.Min(mn, w); mx = Vector3.Max(mx, w);
                }
            }
            return new
            {
                type = b.Type.ToString(),
                box_min = Util.V3(b.BoxMin),
                box_max = Util.V3(b.BoxMax),
                translation = Util.V3(m.TranslationVector),
                vertices = nverts,
                polygons = npolys,
                materials = mats.ToArray(),
                box_consistent = boxOk,
                geometry_min = nverts > 0 || !(b is BoundComposite || b is BoundGeometry) ? Util.V3(mn) : null,
                geometry_max = nverts > 0 || !(b is BoundComposite || b is BoundGeometry) ? Util.V3(mx) : null,
                children,
            };
        }

        private static IEnumerable<Vector3> Corners(Vector3 a, Vector3 b)
        {
            for (int i = 0; i < 8; i++)
                yield return new Vector3((i & 1) == 0 ? a.X : b.X, (i & 2) == 0 ? a.Y : b.Y, (i & 4) == 0 ? a.Z : b.Z);
        }

        private static object DescribeYtd(YtdFile ytd)
        {
            var t = ytd.TextureDict?.Textures?.data_items ?? new Texture[0];
            return new
            {
                type = "ytd",
                textures = t.Select(x => new { name = x.Name?.ToLowerInvariant(), width = (int)x.Width, height = (int)x.Height, format = x.Format.ToString(), mips = (int)x.Levels, data_size = x.Data?.FullData?.Length ?? 0 }).ToArray(),
            };
        }

        private static string H(MetaHash h) { var s = JenkIndex.TryGetString(h); return string.IsNullOrEmpty(s) ? ("hash_" + ((uint)h).ToString("X8")) : s; }

        private static object DescribeYtyp(YtypFile ytyp)
        {
            var list = new List<object>();
            foreach (var a in ytyp.AllArchetypes ?? new Archetype[0])
            {
                var d = a._BaseArchetypeDef;
                object mlo = null;
                if (a is MloArchetype ma)
                {
                    mlo = new
                    {
                        entities = ma.entities?.Select(e => new { archetype = H(e._Data.archetypeName), position = Util.V3(e._Data.position), flags = e._Data.flags }).ToArray(),
                        rooms = ma.rooms?.Select(r => new { name = r.RoomName, bb_min = Util.V3(r.BBMin), bb_max = Util.V3(r.BBMax), attached = r.AttachedObjects, portal_count = r._Data.portalCount, flags = r._Data.flags }).ToArray(),
                        portals = ma.portals?.Length ?? 0,
                    };
                }
                list.Add(new
                {
                    kind = a.Type.ToString(),
                    name = H(d.name),
                    asset_name = H(d.assetName),
                    asset_type = d.assetType.ToString(),
                    texture_dictionary = ((uint)d.textureDictionary) == 0 ? "" : H(d.textureDictionary),
                    physics_dictionary = ((uint)d.physicsDictionary) == 0 ? "" : H(d.physicsDictionary),
                    drawable_dictionary = ((uint)d.drawableDictionary) == 0 ? "" : H(d.drawableDictionary),
                    flags = d.flags,
                    lod_dist = d.lodDist,
                    hd_texture_dist = d.hdTextureDist,
                    bb_min = Util.V3(d.bbMin),
                    bb_max = Util.V3(d.bbMax),
                    bs_center = Util.V3(d.bsCentre),
                    bs_radius = d.bsRadius,
                    mlo,
                });
            }
            return new { type = "ytyp", name = H(ytyp._CMapTypes.name), archetypes = list };
        }

        private static object DescribeYmap(YmapFile ymap)
        {
            return new
            {
                type = "ymap",
                name = H(ymap._CMapData.name),
                flags = ymap._CMapData.flags,
                content_flags = ymap._CMapData.contentFlags,
                entities = (ymap.AllEntities ?? new YmapEntityDef[0]).Select(e => new
                {
                    archetype = H(e._CEntityDef.archetypeName),
                    position = Util.V3(e._CEntityDef.position),
                    rotation = Util.V4(e._CEntityDef.rotation),
                    flags = e._CEntityDef.flags,
                    lod_dist = e._CEntityDef.lodDist,
                    mlo = e.MloInstance != null,
                }).ToArray(),
                streaming_extents = new[] { Util.V3(ymap._CMapData.streamingExtentsMin), Util.V3(ymap._CMapData.streamingExtentsMax) },
                entities_extents = new[] { Util.V3(ymap._CMapData.entitiesExtentsMin), Util.V3(ymap._CMapData.entitiesExtentsMax) },
            };
        }
    }
}
