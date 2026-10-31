using System;
using System.IO;
using System.Linq;
using System.Reflection;

namespace MioGtaTool
{
    public static class Program
    {
        public const string Version = "1.0.0";

        public static string CodeWalkerCommit
        {
            get
            {
                var attr = typeof(Program).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
                    .FirstOrDefault(a => a.Key == "CodeWalkerCommit");
                return attr?.Value ?? "inconnu";
            }
        }

        private const string Help = @"MioGtaTool " + Version + @" - outil compagnon de Mio Mapping Studio (base sur CodeWalker.Core)

Commandes :
  version
  index      --gta DIR --out FICHIER.jsonl [--gen9] [--include-mods] [--embedded] [--cancel-file F]
  signature  --gta DIR [--gen9] [--include-mods]
  extract    --gta DIR --requests REQ.json --out DOSSIER [--gen9] [--cancel-file F]
  build-ytd  --manifest MANIFESTE.json --out FICHIER.ytd [--gen9]
  xml2bin    --in FICHIER.ydr.xml|.ytyp.xml|.ybn.xml|.ytd.xml|.ymap.xml [--out FICHIER] [--gen9]
  verify     --file F [--file F2 ...] [--gen9]
  make-ymap  --spec SPEC.json --ytyp FICHIER.ytyp --out FICHIER.ymap
  dev-make-rpf --spec SPEC.json --out DOSSIER      (tests uniquement : archives OPEN non chiffrees)

Options communes : --no-keys (tests : n'ouvre que les archives non chiffrees).
L'installation GTA V n'est jamais modifiee : toutes les commandes la lisent seulement.
Sortie : une ligne JSON par evenement (progress / log / result).";

        public static int Main(string[] argv)
        {
            try
            {
                var args = new Args(argv);
                switch (args.Command)
                {
                    case "version":
                        Out.Result(new { tool = "MioGtaTool", version = Version, codewalker_commit = CodeWalkerCommit, runtime = Environment.Version.ToString() });
                        return 0;
                    case "index": return IndexCommand.Run(args);
                    case "signature":
                        Out.Result(new { signature = IndexCommand.ComputeSignature(args.Require("gta"), args.Flag("include-mods"), args.Flag("gen9")) });
                        return 0;
                    case "extract": return ExtractCommand.Run(args);
                    case "build-ytd": return BuildYtdCommand.Run(args);
                    case "xml2bin": return Xml2BinCommand.Run(args);
                    case "verify": return VerifyCommand.Run(args);
                    case "make-ymap": return MakeYmapCommand.Run(args);
                    case "dev-make-rpf": return DevMakeRpfCommand.Run(args);
                    case "help":
                    case "--help":
                    case "-h":
                        Console.WriteLine(Help);
                        return 0;
                    default:
                        Out.Fail($"Commande inconnue : {args.Command}");
                        Console.Error.WriteLine(Help);
                        return 2;
                }
            }
            catch (ToolException ex)
            {
                Out.Fail(ex.Message);
                return ex.ExitCode;
            }
            catch (Exception ex)
            {
                var inner = ex is TargetInvocationException tie && tie.InnerException != null ? tie.InnerException : ex;
                Out.Fail(inner.GetType().Name + " : " + inner.Message);
                Console.Error.WriteLine(inner.ToString());
                return 1;
            }
        }
    }
}
