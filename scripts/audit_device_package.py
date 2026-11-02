#!/usr/bin/env python3
"""Audita (só leitura) o pacote "FiberCore OLT Multivendor AllInOne v2": integridade (SHA256SUMS), contagens do manifesto de ativos, existência dos arquivos e varredura dos SVG.
Trata o conteúdo como DADO: não executa nada dele. Uso: python3 -I scripts/audit_device_package.py <pasta-do-pacote-extraído> <zip> <sha256-esperado-do-zip>. Sai 0 só se tudo confere, inclusive que a pasta é EXATAMENTE o conteúdo do zip
(cada membro igual ao arquivo extraído, nenhum arquivo a mais ou a menos) e que o zip tem o SHA-256 esperado."""
import collections, hashlib, json, os, re, sys, zipfile

UNSAFE = re.compile(r"<script|\son\w+\s*=|javascript:|href\s*=\s*[\"']\s*(?:https?:)?//|<foreignObject|<iframe|<object|<embed|<image[^>]+href\s*=\s*[\"']\s*(?:https?:)?//", re.I)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


SEGMENT = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9_. -]*[A-Za-z0-9_-])?$")


def safe_member(name):
    """Forma portátil canônica: relativo, `/` como único separador, e cada segmento começa com letra/dígito/`_`, só usa letras, dígitos, `_`, `.`, `-` e espaço e NÃO termina em ponto nem espaço
    (o Windows os remove e `.. ` viraria `..`). Recusa tudo o mais, em qualquer sistema que extraia: `\\`, UNC, letra de drive, NUL, segmento vazio, `.`, `..` e suas variantes."""
    return bool(name) and not name.startswith("/") and all(SEGMENT.match(seg) for seg in name.split("/")) and all(seg.strip(". ") != "" for seg in name.split("/"))


def bind_to_zip(root, zip_path):
    """A pasta auditada tem de ser o conteúdo do zip, byte a byte: sem isso um OK valeria para outro material."""
    with zipfile.ZipFile(zip_path) as z:
        everything = [i.filename.rstrip("/") if i.is_dir() else i.filename for i in z.infolist()]   # arquivos E diretórios: nome repetido ou caminho fora da forma portátil invalida o zip
        if len(set(everything)) != len(everything) or any(not safe_member(n) for n in everything):
            return {"members": len(everything), "same_as_folder": False, "why": "o zip tem nomes de entrada repetidos ou caminhos fora da forma portátil"}
        infos = [i for i in z.infolist() if not i.is_dir()]
        names = [i.filename for i in infos]
        members = {i.filename: hashlib.sha256(z.read(i)).hexdigest() for i in infos}
    top = {n.split("/", 1)[0] for n in members}
    if len(top) != 1 or any("/" not in n for n in members):
        return {"members": len(members), "same_as_folder": False, "why": "o zip não tem uma única pasta raiz"}
    base = os.path.basename(os.path.normpath(root))
    prefix = top.pop()
    if base != prefix:
        return {"members": len(members), "same_as_folder": False, "why": "a pasta não tem o nome da raiz do zip"}
    on_disk = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            full = os.path.join(d, f)
            on_disk[prefix + "/" + os.path.relpath(full, root).replace(os.sep, "/")] = sha(full)
    diff = sorted({n for n in members if members[n] != on_disk.get(n)} | (set(on_disk) - set(members)))
    # a estrutura também tem de bater: os diretórios (inclusive os VAZIOS) que o zip declara existem na pasta, e a pasta não tem diretório vazio que o zip não declare
    implied = {"/".join(n.split("/")[:k]) for n in members for k in range(1, len(n.split("/")))}
    zip_dirs = {n.rstrip("/") for n in everything if n not in members and n.rstrip("/") not in members}
    disk_dirs = {prefix + ("/" + os.path.relpath(os.path.join(d, x), root).replace(os.sep, "/")) for d, ds, _ in os.walk(root) for x in ds}
    disk_empty = disk_dirs - implied
    zip_empty = zip_dirs - implied
    dirs_diff = sorted((zip_empty - disk_dirs) | (disk_empty - zip_dirs))
    return {"members": len(members), "same_as_folder": not diff and not dirs_diff, "different": diff[:10], "different_dirs": dirs_diff[:10]}


def main(root, zip_path, expected_zip_sha):
    out, ok = {}, True
    out["zip_sha256"] = sha(zip_path)
    out["zip_sha256_expected_ok"] = out["zip_sha256"] == expected_zip_sha
    ok &= out["zip_sha256_expected_ok"]
    out["zip_bound_to_folder"] = bind_to_zip(root, zip_path)
    ok &= out["zip_bound_to_folder"]["same_as_folder"]
    sums = [l.split(None, 1) for l in open(os.path.join(root, "SHA256SUMS.txt"), encoding="utf-8").read().splitlines() if l.strip()]
    bad = [n.strip().lstrip("*") for h, n in sums if not os.path.exists(os.path.join(root, n.strip().lstrip("*"))) or sha(os.path.join(root, n.strip().lstrip("*"))) != h]
    out["checksums"] = {"listed": len(sums), "failed": len(bad)}
    ok &= not bad
    m = json.load(open(os.path.join(root, "visual", "asset-manifest.json"), encoding="utf-8"))
    A = m["assets"]
    ids = [a["asset_id"] for a in A]
    out["manifest"] = {"declared": m["count"], "entries": len(A), "unique_ids": len(set(ids)) == len(ids),
                       "by_type_status": {f"{k[0]}/{k[1]}": v for k, v in collections.Counter((a["device_type"], a["status"]) for a in A).items()},
                       "vendors": sorted({a["vendor"] for a in A}), "accuracy": dict(collections.Counter(a["accuracy"] for a in A)),
                       "ids_sha256": hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()}
    ok &= m["count"] == len(A) and len(set(ids)) == len(ids)
    vis = os.path.join(root, "visual")
    missing = [(a["asset_id"], k) for a in A for k in ("svg", "png") if not os.path.exists(os.path.join(vis, a[k].lstrip("/").removeprefix("visual/")))]
    ref = {a["asset_id"] for a in A if a["status"] == "REFERENCE_REUSE_EXISTING"}   # a referência aponta para o painel real já existente: sem arquivo próprio, por desenho
    unexpected = [x for x in missing if x[0] not in ref]
    ok &= not unexpected
    out["files"] = {"unexpected_missing": unexpected, "svg": sum(len(f) for _, _, f in os.walk(os.path.join(vis, "svg")) if f), "png": sum(len(f) for _, _, f in os.walk(os.path.join(vis, "png")) if f), "missing_by_design": [x for x in missing if x[0] in ref]}
    suspects = []
    for d, _, fs in os.walk(os.path.join(vis, "svg")):
        for f in fs:
            if f.endswith(".svg") and UNSAFE.search(open(os.path.join(d, f), encoding="utf-8", errors="replace").read()):
                suspects.append(f)
    out["svg_unsafe"] = suspects
    ok &= not suspects
    out["result"] = "OK" if ok else "FALHOU"
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
