"""Before/after proof for the GhosttySharp.Native targets fix.

Publishes a console app that references Sentry 6.11.1 and the GhosttySharp.Native
package for this OS, once with the published 0.6.1 package ("before") and once with
0.6.1 repacked with the patched targets files ("after"). Prints what each publish did.

Usage: python3 prove.py <path to RoyalTerminal checkout with the fix> <rid>
"""
import json, os, pathlib, platform, shutil, subprocess, sys, urllib.request, zipfile

repo = pathlib.Path(sys.argv[1]).resolve()
rid = sys.argv[2]
plat = {"Windows": "Win64", "Darwin": "OSX", "Linux": "Linux64"}[platform.system()]
pkg_id = f"RoyalApps.RoyalTerminal.GhosttySharp.Native.{plat}"
version, fixed = "0.6.1", "0.6.1-fixed"
work = pathlib.Path(__file__).resolve().parent / f"work-{rid}"
shutil.rmtree(work, ignore_errors=True)
feed = work / "feed"
feed.mkdir(parents=True)

# Original package from nuget.org, and a copy with the patched targets files.
orig = feed / f"{pkg_id.lower()}.{version}.nupkg"
url = f"https://api.nuget.org/v3-flatcontainer/{pkg_id.lower()}/{version}/{pkg_id.lower()}.{version}.nupkg"
urllib.request.urlretrieve(url, orig)
src = repo / "src" / f"RoyalTerminal.GhosttySharp.Native.{plat}"
with zipfile.ZipFile(orig) as zin, zipfile.ZipFile(feed / f"{pkg_id.lower()}.{fixed}.nupkg", "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        name = item.filename
        if name == ".signature.p7s":
            continue
        data = zin.read(name)
        if name.endswith(".nuspec"):
            data = data.replace(f"<version>{version}</version>".encode(), f"<version>{fixed}</version>".encode())
        for folder in ("build", "buildTransitive"):
            if name == f"{folder}/{pkg_id}.targets":
                data = (src / folder / f"RoyalTerminal.GhosttySharp.Native.{plat}.targets").read_bytes()
        zout.writestr(item, data)
orig.unlink()  # nuget.org stays the source for "before"


def run(label, pkg_version):
    proj = work / label
    proj.mkdir()
    (proj / "Repro.csproj").write_text(f"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net10.0</TargetFramework>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Sentry" Version="6.11.1" />
    <PackageReference Include="{pkg_id}" Version="{pkg_version}" />
  </ItemGroup>
</Project>
""")
    (proj / "Program.cs").write_text("System.Console.WriteLine(\"repro\");\n")
    (proj / "nuget.config").write_text(f"""<configuration>
  <packageSources>
    <clear />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
    <add key="local" value="{feed}" />
  </packageSources>
</configuration>
""")
    env = dict(os.environ, NUGET_PACKAGES=str(work / "packages"), DOTNET_CLI_TELEMETRY_OPTOUT="1")
    subprocess.run(["dotnet", "restore", "-r", rid], cwd=proj, env=env, check=True, capture_output=True)
    items = json.loads(subprocess.run(
        ["dotnet", "msbuild", "-getItem:NativeLibrary", "-getItem:None", f"-p:RuntimeIdentifier={rid}"],
        cwd=proj, env=env, check=True, capture_output=True, text=True).stdout)["Items"]
    native = sorted(i["Filename"] + i["Extension"] for i in items.get("NativeLibrary", []))
    copied = sorted(i["Filename"] + i["Extension"] for i in items.get("None", []) if i.get("CopyToOutputDirectory"))
    pub = subprocess.run(["dotnet", "publish", "-r", rid, "--no-restore", "-o", "out"],
                         cwd=proj, env=env, capture_output=True, text=True)
    errors = sorted({l.split(": error ")[1].split(" [")[0] for l in pub.stdout.splitlines() if ": error " in l})
    out = proj / "out"
    files = sorted(p.name for p in out.iterdir()) if out.exists() else []
    print(f"## {label} ({pkg_id} {pkg_version}, publish -r {rid}, {platform.system()})")
    print(f"NativeLibrary items : {native}")
    print(f"None items copied   : {copied}")
    print(f"publish exit code   : {pub.returncode}")
    for e in errors:
        print(f"  error {e}")
    print(f"native files in out : {[f for f in files if f.startswith(('ghostty', 'libghostty')) or f.endswith(('.lib', '.a'))]}")
    print()
    return pub.returncode


before = run("before", version)
after = run("after", fixed)
sys.exit(0 if after == 0 else 1)
