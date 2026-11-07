import re, json, base64, sys, os
D = sys.argv[1]; OUT = sys.argv[2]; OL = sys.argv[3]
ORDER = ["Main","Welcome","Stages","Account","Meet","Name","Vehicle","Night","Ladder","Privacy","Permissions","Contact","Pair","Voice","Calibrate","Plan","Route","Drive","Home","Camera","Trips","Insights","Settings"]
BLOB = {
 "bb73e1b39dabf3b35d036c39c5cdd1c1":"idle","be4e6418a0a3f416c7aca695e46d9667":"hello","4af7029f76e815daac75989af4aba986":"thinking",
 "fa546fa5fa5789063fdee0a2beebd5b2":"sleepy","57efe0ac85b17a5178828ea07e413fad":"wake","f6f6ffbf7935cbf40e40727534b41f50":"celebrate",
 "5e3b2ef0811cd96b7ab97688744ccbd7":"peek","e5ad4d3fd744c75caea7c6c78782a441":"driving","070226ec21792f2c9c1824851ca1ff5a":"cup"}
IMG = {n: "data:image/webp;base64," + base64.b64encode(open(f"{OL}/{n}.webp","rb").read()).decode() for n in BLOB.values()}
# The default Ollie (idle, hello) is the flat one now (docs/REDESIGN_PLAN.md);
# the other moods stay painted until they get flat versions too.
FLAT = "data:image/svg+xml;base64," + base64.b64encode(re.sub(r"<!--.*?-->", "", open(f"{OL}/flat.svg", encoding="utf-8").read(), flags=re.S).encode()).decode()
IMG["idle"] = IMG["hello"] = FLAT

def scope(css, sid):
    out = []; i = 0; n = len(css)
    while i < n:
        j = css.find("{", i)
        if j < 0: break
        head = css[i:j].strip()
        depth = 0; k = j
        while k < n:
            if css[k] == "{": depth += 1
            elif css[k] == "}":
                depth -= 1
                if depth == 0: break
            k += 1
        body = css[j+1:k]
        if head.startswith("@keyframes"):
            out.append(f"{head}{{{body}}}")
        elif head.startswith("@media"):
            out.append(f"{head}{{{scope(body, sid)}}}")
        else:
            sels = []
            for s in head.split(","):
                s = s.strip()
                if s == "body": sels.append(sid)
                else: sels.append(f"{sid} {s}")
            out.append(",".join(sels) + "{" + body + "}")
        i = k + 1
    return "\n".join(out)

styles = []; tpls = []
for name in ORDER:
    src = open(f"{D}/{name}.dc.html", encoding="utf-8").read()
    helmet = re.search(r"<helmet>(.*?)</helmet>", src, re.S).group(1)
    css = "\n".join(re.findall(r"<style>(.*?)</style>", helmet, re.S))
    body = re.search(r"</helmet>(.*?)</x-dc>", src, re.S).group(1)
    if name == "Night":
        body = re.sub(r'(<div style="display:flex;justify-content:space-between">)\s*<sc-for list="\{\{days\}\}".*?</sc-for>', r'<div id="nDays" style="display:flex;justify-content:space-between">', body, flags=re.S)
        body = re.sub(r'(<div style="display:grid;grid-template-columns:repeat\(4,minmax\(0,1fr\)\);gap:8px">)\s*<sc-for list="\{\{presets\}\}".*?</sc-for>', r'<div id="nPresets" style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px">', body, flags=re.S)
        body = re.sub(r'<b ([^>]*)>\{\{start\}\}</b>', r'<b id="nStart" \1></b>', body)
        body = re.sub(r'<b ([^>]*)>\{\{end\}\}</b>', r'<b id="nEnd" \1></b>', body)
        body = re.sub(r'<p ([^>]*)>\{\{hardest\}\}</p>', r'<p id="nHard" \1></p>', body)
        body = re.sub(r'<sc-for list="\{\{segs\}\}".*?</sc-for>', '<div id="nSegs" style="position:absolute;inset:0"></div>', body, flags=re.S)
    if name == "Ladder":
        tr = "position:relative;width:50px;height:30px;flex-shrink:0;border:0;border-radius:99px;padding:0;background:#E8D7AE;transition:background .2s"
        kn = "position:absolute;top:3px;left:3px;width:24px;height:24px;border-radius:50%;background:#F2EEE8;transition:transform .25s cubic-bezier(.3,1.5,.5,1)"
        body = re.sub(r'<button role="switch" aria-checked="\{\{(\w+)\}\}" aria-label="([^"]+)" onClick="\{\{\w+\}\}" style="\{\{\w+\}\}"><span style="\{\{\w+\}\}"></span></button>',
                      lambda m: f'<button type="button" role="switch" data-tog="{m.group(1)}" aria-checked="true" aria-label="{m.group(2)}" style="{tr}"><span style="{kn}"></span></button>', body)
    if name == "Voice":
        body = body.replace('<img src="{{cur.src}}" alt=""', '<img id="vAv" alt=""')
        body = body.replace('<p class="vc-say"', '<p id="vSay" class="vc-say"').replace('>{{cur.line}}</p>', '></p>')
        body = re.sub(r'(<div style="display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\);gap:12px;margin-top:18px">)\s*<sc-for list="\{\{cards\}\}".*?</button>\s*</sc-for>', r'<div id="vCards" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:18px">', body, flags=re.S)
    if name in ("Home", "Trips", "Insights"):
        body = re.sub(r'height:(1520|1240)px;box-sizing:border-box;position:relative;overflow:hidden;', 'min-height:844px;flex:1 0 auto;display:flex;flex-direction:column;box-sizing:border-box;position:relative;overflow:clip;', body, count=1)
        # The bar sits at the bottom of the screen even when the content is
        # short (or still loading), and stays sticky when it's long.
        body = body.replace('<nav style="position:absolute;left:16px;right:16px;bottom:26px;', '<div aria-hidden="true" style="flex:1 0 24px"></div><nav style="position:sticky;z-index:20;margin:0 ' + ('16px' if name == "Home" else '0') + ';bottom:26px;')
        body = re.sub(r'(</nav>)', r'\1<div style="height:26px"></div>', body, count=1)
    assert "{{" not in body and "<sc-" not in body, (name, re.findall(r".{40}\{\{.{30}", body)[:3])
    for bid, n in BLOB.items():
        body = body.replace(f"/_blob/{bid}", IMG[n])
    body = re.sub(r'href="(\w+)\.dc\.html"', r'href="#\1" data-go="\1"', body)
    styles.append(f"/* {name} */\n" + scope(css, f"#s-{name}"))
    tpls.append(f'<template id="t-{name}">{body}</template>')

shell = open(os.path.join(os.path.dirname(__file__), "shell.html"), encoding="utf-8").read()
dyn = open(os.path.join(os.path.dirname(__file__), "dyn.js"), encoding="utf-8").read()
dyn += chr(10) + open(os.path.join(os.path.dirname(__file__), "route.js"), encoding="utf-8").read()
dyn += chr(10) + open(os.path.join(os.path.dirname(__file__), "camera.js"), encoding="utf-8").read()
dyn += chr(10) + open(os.path.join(os.path.dirname(__file__), "calibrate.js"), encoding="utf-8").read()
live = open(os.path.join(os.path.dirname(__file__), "live.js"), encoding="utf-8").read()
live += chr(10) + open(os.path.join(os.path.dirname(__file__), "account.js"), encoding="utf-8").read()
live += chr(10) + open(os.path.join(os.path.dirname(__file__), "visit.js"), encoding="utf-8").read().replace(
    "/*__ROUTES__*/[]", open(os.path.join(os.path.dirname(__file__), "routes_kr.json"), encoding="utf-8").read())
live += chr(10) + open(os.path.join(os.path.dirname(__file__), "api.js"), encoding="utf-8").read()
live += chr(10) + open(os.path.join(os.path.dirname(__file__), "sync.js"), encoding="utf-8").read()
live += chr(10) + open(os.path.join(os.path.dirname(__file__), "overlay.js"), encoding="utf-8").read()
html = (shell.replace("/*__STYLES__*/", "\n".join(styles))
             .replace("/*__LIVE__*/", live)
             .replace("<!--__TEMPLATES__-->", "\n".join(tpls))
             .replace("/*__IMG__*/", "const IMG=" + json.dumps(IMG) + ";\n" + dyn)
             .replace("/*__ORDER__*/", json.dumps(ORDER))
             .replace("<!--__ICON__-->", '<link rel="icon" href="data:image/svg+xml;base64,' + base64.b64encode(re.sub(r"<!--.*?-->", "", open(f"{OL}/icon.svg", encoding="utf-8").read(), flags=re.S).encode()).decode() + '">')
             .replace("/*__KO__*/", open(os.path.join(os.path.dirname(__file__), "ko.json"), encoding="utf-8").read()))
# Fonts go inside the file, like the images, so the one file is the whole app:
# it opens from disk, from the Pi or in Capacitor with nothing beside it.
FONTS = os.path.join(os.path.dirname(__file__), "..", "fonts")
html = re.sub(r"url\(fonts/([\w.-]+\.woff2)\)", lambda m: "url(data:font/woff2;base64," + base64.b64encode(open(os.path.join(FONTS, m.group(1)), "rb").read()).decode() + ")", html)
# The Kakao map key (public, but locked to registered web addresses) goes only
# into builds under www/, which are not in git. Bamnun_app.html stays key-free
# and asks the device (/api/config). The secret REST key never goes in at all.
ENV = {}
try:
    for line in open(os.path.join(os.path.dirname(__file__), "..", ".env"), encoding="utf-8"):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            ENV[k.strip()] = v.strip().strip("'\"")
except OSError:
    pass
def _jwt_role(key):
    """The payload of a legacy JWT key, as text ('' if it isn't one)."""
    try:
        part = key.split(".")[1]
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)).decode("utf-8", "replace")
    except (IndexError, ValueError):
        return ""
# OUT may list several paths separated by commas; all get the same build.
for out in OUT.split(","):
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    page = html
    if ENV.get("KAKAO_JS_KEY") and "www" in os.path.normpath(out).split(os.sep):
        page = page.replace("<script>", "<script>window.BN_KAKAO_JS=" + json.dumps(ENV["KAKAO_JS_KEY"]) + ";", 1)
    # Supabase: the project URL and the public anon (publishable) key, which
    # are safe in an app because Row Level Security guards every row. Like
    # the Kakao key, only builds under www/ get them. The service role key
    # must never be in .env for the app, and is refused here.
    sb_url, sb_key = ENV.get("SUPABASE_URL", "").rstrip("/"), ENV.get("SUPABASE_ANON_KEY", "")
    if sb_key.startswith("sb_secret_") or '"service_role"' in _jwt_role(sb_key):
        sys.exit("SUPABASE_ANON_KEY in frontend/.env is a secret/service role key. Use the anon or publishable key.")
    if sb_url and sb_key and "www" in os.path.normpath(out).split(os.sep):
        page = page.replace("<script>", "<script>window.BN_SUPABASE=" + json.dumps({"url": sb_url, "key": sb_key}) + ";", 1)
    open(out, "w", encoding="utf-8", newline="\n").write(page)
    # The booth's staff remote (staff.html), next to the website's page.
    if sb_url and sb_key and "www" in os.path.normpath(out).split(os.sep):
        staff = open(os.path.join(os.path.dirname(__file__), "staff.html"), encoding="utf-8").read()
        staff = staff.replace("__SB_URL__", sb_url).replace("__SB_KEY__", sb_key)
        open(os.path.join(os.path.dirname(out), "staff.html"), "w", encoding="utf-8", newline="\n").write(staff)
print("ok", len(html))
