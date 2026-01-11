from flask import Flask, request, jsonify
from pathlib import Path
import subprocess
import datetime
import json
from archive_daily import archive
from build_daily_char_meta_map import (
    parse_meta_from_text,
    count_chars_from_text,
)


app = Flask(__name__)

# ===== 路径统一从这里出发，避免写错 =====
BASE_DIR = Path(__file__).resolve().parent
DEBUG_FILE = BASE_DIR / "_agent_debug.json"
INBOX_DIR = BASE_DIR / "agent_inbox"

def scp_to_server(*paths):
    """
    把指定文件 scp 到服务器
    """
    remote = "root@139.224.80.186:/var/www/html/calendar"

    cmd = ["scp", *map(str, paths), remote]

    # 同步执行，失败就抛异常（方便你发现问题）
    subprocess.run(cmd, check=True)


@app.after_request
def add_cors_headers(resp):
    # 允许你的网页来源访问（先用 * 省事；后面想收紧再改成具体 origin）
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.get("/ping")
def ping():
    """
    用来测试 agent 是否存活
    浏览器访问 http://127.0.0.1:8787/ping
    """
    return {"ok": True, "msg": "agent alive"}


@app.post("/echo")
def echo():
    """
    最小 POST 测试接口：
    - 接收 JSON
    - 打印
    - 顺手写到一个 debug 文件
    """
    data = request.get_json(force=True)

    payload = {
        "received_at": datetime.datetime.now().isoformat(),
        "data": data,
    }

    # 写一个本地文件，确认 agent 真能落盘
    DEBUG_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("=== RECEIVED FROM WEB ===")
    print(payload)

    return jsonify({"ok": True})


@app.post("/save")
def save():
    """
    保存传入文本到 agent_inbox 目录
    """
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    if text is None or str(text).strip() == "":
        return jsonify({"error": "empty text"}), 400

    INBOX_DIR.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = INBOX_DIR / f"{ts}.txt"
    file_path.write_text(str(text), encoding="utf-8")

    # 直接消费收到的文本，完成 meta/char map patch
    meta_map_path = BASE_DIR / "daily_meta_map.json"
    char_map_path = BASE_DIR / "daily_char_map.json"

    if meta_map_path.exists():
        daily_meta_map = json.loads(meta_map_path.read_text(encoding="utf-8"))
    else:
        daily_meta_map = {}

    if char_map_path.exists():
        daily_char_map = json.loads(char_map_path.read_text(encoding="utf-8"))
    else:
        daily_char_map = {}

    content = str(text).splitlines()
    log_date = content[0].strip()
    archive(content)

    meta = parse_meta_from_text(str(text))
    char_count = count_chars_from_text(str(text))

    daily_meta_map[log_date] = meta
    daily_char_map[log_date] = char_count

    meta_map_path.write_text(
        json.dumps(daily_meta_map, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    char_map_path.write_text(
        json.dumps(daily_char_map, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # === 自动 scp 到服务器 ===
    scp_to_server(meta_map_path, char_map_path)

    return jsonify({"ok": True})


@app.post("/consume_inbox")
def consume_inbox():
    """
    消费 agent_inbox 中的 txt：
    - 解析 meta
    - 统计字符数
    - patch 到 daily_meta_map.json / daily_char_map.json
    """
    INBOX_DIR.mkdir(exist_ok=True)

    meta_map_path = BASE_DIR / "daily_meta_map.json"
    char_map_path = BASE_DIR / "daily_char_map.json"

    # 读取已有 map（不存在就初始化）
    if meta_map_path.exists():
        daily_meta_map = json.loads(meta_map_path.read_text(encoding="utf-8"))
    else:
        daily_meta_map = {}

    if char_map_path.exists():
        daily_char_map = json.loads(char_map_path.read_text(encoding="utf-8"))
    else:
        daily_char_map = {}

    processed = []
    errors = []

    for txt in sorted(INBOX_DIR.glob("*.txt")):
        try:
            text = txt.read_text(encoding="utf-8")

            # 用“今天”作为日期（你之后想改成从网页传，也很容易）
            today = datetime.date.today().isoformat()

            meta = parse_meta_from_text(text)
            char_count = count_chars_from_text(text)

            daily_meta_map[today] = meta
            daily_char_map[today] = char_count

            processed.append(txt.name)

            # 处理成功就删除（或你也可以 move 到 processed/）
            txt.unlink()

        except Exception as e:
            errors.append({
                "file": txt.name,
                "error": str(e),
            })

    # 写回 map
    meta_map_path.write_text(
        json.dumps(daily_meta_map, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    char_map_path.write_text(
        json.dumps(daily_char_map, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    return jsonify({
        "ok": True,
        "processed": processed,
        "errors": errors,
    })



if __name__ == "__main__":
    # 只监听本机，安全
    app.run(host="127.0.0.1", port=8787, debug=True)
