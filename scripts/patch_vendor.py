"""Apply the bounded, local Potree-Next prototype fixes to pinned originals."""

from pathlib import Path
import argparse
import difflib
import zipfile

BASE = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=BASE / "dist")
args = parser.parse_args()
VENDOR = args.output / "vendor/potree-next"
patches = {}

patches["src/potree/octree/PointCloudOctree.js"] = [
    (
        "\t\t\tlet {node, weight} = element;\n",
        "\t\t\tlet {node, weight} = element;\n\n\t\t\t// Local prototype: enforce the budget assigned by the upstream renderer.\n\t\t\tif (numPoints + node.numPoints > this.pointBudget) continue;\n",
    ),
]
patches["src/potree/octree/loader/PotreeLoader.js"] = [
    (
        "\t\tlet buffer = await response.arrayBuffer();\n\n\t\tthis.parseHierarchy(node, buffer);",
        "\t\tif (response.status !== 206) throw new Error(`Hierarchy Range HTTP ${response.status}`);\n\t\tlet buffer = await response.arrayBuffer();\n\t\tif (buffer.byteLength !== Number(node.hierarchyByteSize)) throw new Error('Incomplete hierarchy Range');\n\n\t\tthis.parseHierarchy(node, buffer);",
    ),
    (
        '\t\t\t\tif(data === "failed"){\n',
        '\t\t\t\tif(data === "failed"){\n\t\t\t\t\tnode.loadAttempts = (node.loadAttempts || 0) + 1;\n\t\t\t\t\tthis.error = `Nie udało się odczytać fragmentu chmury ${node.name}. Sprawdź HTTP Range i odśwież stronę.`;\n',
    ),
    (
        "\t\t}catch(e){\n\t\t\tdebugger;",
        "\t\t}catch(e){\n\t\t\tnode.loadAttempts = (node.loadAttempts || 0) + 1;\n\t\t\tthis.error = `Nie udało się odczytać hierarchii ${node.name}: ${e.message || e}`;",
    ),
    (
        "\t\tlet response = await fetch(url);\n\t\tlet metadata = await response.json();",
        "\t\tlet response = await fetch(url);\n\t\tif (!response.ok) throw new Error(`Metadane chmury: HTTP ${response.status}`);\n\t\tlet metadata = await response.json();",
    ),
]
patches["src/potree/octree/loader/DecoderWorker_default.js"] = [
    (
        "\t\tbuffer = await response.arrayBuffer();",
        "\t\tif (response.status !== 206) throw new Error(`Point Range HTTP ${response.status}`);\n\t\tbuffer = await response.arrayBuffer();\n\t\tif (buffer.byteLength !== Number(byteSize)) throw new Error('Incomplete point Range');",
    ),
]
patches["src/renderer/Renderer.js"] = [
    (
        "\t\tx = Math.max(x, 0);\n\t\ty = Math.max(y, 0);",
        "\t\t// A resize can leave the pointer outside the new picking texture.\n\t\tif (x >= texture.width || y >= texture.height || width > texture.width || height > texture.height) {\n\t\t\treturn new ArrayBuffer(width * height * 4);\n\t\t}\n\t\tx = Math.max(0, Math.min(Math.floor(x), texture.width - width));\n\t\ty = Math.max(0, Math.min(Math.floor(y), texture.height - height));",
    ),
]
patches["src/init.js"] = [
    (
        'import * as ProgressiveLoader from "./modules/progressive_loader/ProgressiveLoader.js";\n',
        "// Local JKTZ prototype uses prepared octrees only; no experimental LAS drop loader.\n",
    ),
    (
        '\t// progressive loader\n\tlet element = document.getElementById("canvas");\n\tProgressiveLoader.install(element, {\n\t\tonSetup: (node) => {\n\t\t\tscene.root.children.push(node)\n\t\t\tconsole.log("setup done");\n\t\t},\n\t\tonProgress: (e) => {\n\t\t\tconsole.log("progress", e);\n\t\t}\n\t});\n',
        "",
    ),
]

diff = []
with zipfile.ZipFile(BASE / "vendor/potree-next.zip") as archive:
    root = archive.namelist()[0].split("/")[0]
    for path, substitutions in patches.items():
        original = archive.read(f"{root}/{path}").decode().replace("\r\n", "\n")
        changed = original
        for before, after in substitutions:
            if changed.count(before) != 1:
                raise ValueError(f"Unexpected pinned source: {path}")
            changed = changed.replace(before, after, 1)
        (VENDOR / path).write_bytes(changed.replace("\n", "\r\n").encode())
        diff.extend(
            difflib.unified_diff(
                original.splitlines(True),
                changed.splitlines(True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
(args.output / "potree-next-local.patch").write_text("".join(diff))
print(f"Applied {len(patches)} local files; saved reproducible diff")
