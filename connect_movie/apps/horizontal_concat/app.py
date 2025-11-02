
# app_streamlit.py
# -*- coding: utf-8 -*-
import streamlit as st
import os, io, tempfile, shutil, subprocess
from pathlib import Path
from typing import List, Tuple

# --- FFmpeg path via imageio-ffmpeg (works on Streamlit Cloud) ---
def get_ffmpeg_exe() -> str:
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        # Fallback: hope system ffmpeg exists (local dev)
        return "ffmpeg"

import imageio_ffmpeg

st.set_page_config(page_title="横動画連結アプリ", layout="wide")

st.title("横動画連結アプリ")

st.markdown("""
**手順**
1. 左のサイドバーで上部字幕や書き出し設定を入力  
2. 下で動画をまとめて選択（複数可）し、順序と各クリップ下部字幕を入力  
3. 「結合して書き出す」を押す  
""")

# --------------- Utils ---------------
def has_ffmpeg() -> bool:
    try:
        ff = get_ffmpeg_exe()
        import subprocess
        subprocess.run([ff, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        return True
    except Exception:
        return False

def ff_esc(text: str) -> str:
    if text is None:
        return ""
    t = text.replace("\\", r"\\\\")
    t = t.replace(":", r"\:")
    t = t.replace("'", r"\'")
    t = t.replace("\n", r"\n")
    return t

# --------------- Sidebar Settings ---------------
st.sidebar.header("共通設定（上部字幕 & 書き出し）")
global_top_text = st.sidebar.text_area("上部字幕（全クリップ共通）", value="", height=80, help="空欄で上部字幕なし")
fs_top = st.sidebar.number_input("上部字幕フォントサイズ（映像高さ×）", value=0.06, step=0.01, min_value=0.01, max_value=0.5)
fs_bottom_default = st.sidebar.number_input("下部字幕フォントサイズ（既定・映像高さ×）", value=0.06, step=0.01, min_value=0.01, max_value=0.5)
margin_top = st.sidebar.number_input("上部の余白(px)", value=40, step=2, min_value=0)
margin_bottom_default = st.sidebar.number_input("下部の余白（既定・px）", value=40, step=2, min_value=0)
box_opacity = st.sidebar.slider("字幕背景の不透明度", 0.0, 1.0, 0.55, 0.05)
crf = st.sidebar.number_input("CRF（画質：16-23推奨）", value=18, step=1, min_value=12, max_value=30)
preset = st.sidebar.selectbox("preset", ["ultrafast","superfast","veryfast","faster","fast","medium","slow","slower","veryslow"], index=5)
output_name = st.sidebar.text_input("出力ファイル名", value="output_joined.mp4")
font_file = st.sidebar.file_uploader("（任意）TrueType/OpenTypeフォントを指定", type=["ttf","otf"], accept_multiple_files=False, help="日本語字幕でフォントを指定したい場合に使用")

st.sidebar.info("⚠️ このアプリはローカル/サーバでの実行を想定しています。stlite（ブラウザのみ）環境では FFmpeg が動作しません。")

# --------------- Inputs: videos ---------------
st.subheader("動画と下部字幕の入力")
uploads = st.file_uploader("動画ファイルを複数選択（順序は後で変更可）", type=["mp4","mov","mkv","avi","m4v","webm"], accept_multiple_files=True)

if "clips" not in st.session_state:
    st.session_state["clips"] = []  # List[dict]
    # dict keys: {"name","data","order","bottom","fs_bottom","margin_bottom"}

def rebuild_from_uploads():
    """Merge new uploads into session_state, preserving any already-entered metadata by matching filename+size."""
    existing = st.session_state["clips"]
    new_items = []
    # Build a set to find duplicates by (name, size) fingerprint
    existing_keys = {(c["name"], len(c["data"])) for c in existing}
    # Append new ones with default metadata
    if uploads:
        start_order = len(existing) + 1
        for f in uploads:
            data_bytes = f.getvalue()
            key = (f.name, len(data_bytes))
            if key not in existing_keys:
                new_items.append({
                    "name": f.name,
                    "data": data_bytes,
                    "order": start_order,
                    "bottom": Path(f.name).stem,
                    "fs_bottom": fs_bottom_default,
                    "margin_bottom": margin_bottom_default,
                })
                start_order += 1
    st.session_state["clips"].extend(new_items)

rebuild_from_uploads()

clips = st.session_state["clips"]
if clips:
    st.caption("順序・各字幕を編集してから下のボタンで書き出してください。")
    # Table-like editor
    cols = st.columns([3,1,3,1,1])
    with cols[0]: st.markdown("**ファイル名**")
    with cols[1]: st.markdown("**順序**")
    with cols[2]: st.markdown("**下部字幕**")
    with cols[3]: st.markdown("**fs**")
    with cols[4]: st.markdown("**余白**")

    # Render each row with widgets
    for i, c in enumerate(clips):
        cols = st.columns([3,1,3,1,1])
        with cols[0]:
            st.text(c["name"])
        with cols[1]:
            c["order"] = st.number_input(f"order_{i}", value=int(c["order"]), min_value=1, step=1, key=f"ord_{i}")
        with cols[2]:
            c["bottom"] = st.text_input(f"bottom_{i}", value=c["bottom"], key=f"bot_{i}")
        with cols[3]:
            c["fs_bottom"] = st.number_input(f"fsb_{i}", value=float(c["fs_bottom"]), min_value=0.01, max_value=0.5, step=0.01, key=f"fsbkey_{i}")
        with cols[4]:
            c["margin_bottom"] = st.number_input(f"mb_{i}", value=int(c["margin_bottom"]), min_value=0, step=2, key=f"mbkey_{i}")
else:
    st.info("動画を選択してください。")

# --------------- Process button ---------------
run = st.button("🎬 結合して書き出す", use_container_width=True)

def run_ffmpeg(cmd: List[str]) -> Tuple[bool, str]:
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        logs = []
        for line in proc.stdout:
            logs.append(line)
        proc.wait()
        ok = proc.returncode == 0
        return ok, "".join(logs)
    except Exception as e:
        return False, f"Exception: {e}"

if run:
    if not has_ffmpeg():
        st.error("FFmpeg が見つかりません。ローカルにインストールし、PATH を通してください。")
    elif not clips:
        st.warning("動画が選択されていません。")
    else:
        # Sort by order
        clips_sorted = sorted(clips, key=lambda x: x["order"])
        with st.spinner("書き出し中...（時間がかかる場合があります）"):
            with tempfile.TemporaryDirectory(prefix="st_join_subs_") as tmpd:
                tmpdir = Path(tmpd)
                # Save optional font
                font_path = None
                if font_file is not None:
                    font_path = tmpdir / font_file.name
                    with open(font_path, "wb") as f:
                        f.write(font_file.getvalue())

                parts = []
                # Render each clip with subtitles
                for idx, c in enumerate(clips_sorted):
                    in_path = tmpdir / f"in_{idx:03d}{Path(c['name']).suffix}"
                    with open(in_path, "wb") as f:
                        f.write(c["data"])

                    top_esc = ff_esc(global_top_text)
                    bottom_esc = ff_esc(c["bottom"] or "")

                    # drawtext filters
                    font_opt = f":fontfile='{font_path.as_posix()}'" if font_path else ""
                    vf_top = ""
                    if global_top_text:
                        vf_top = (
                            f"drawtext=text='{top_esc}'{font_opt}:"
                            f"x=(w-text_w)/2:y={int(c.get('margin_top', 0) or 0) + int(margin_top)}:"
                            f"fontsize=h*{fs_top}:"
                            f"fontcolor=white:box=1:boxcolor=black@{box_opacity}:boxborderw=10"
                        )
                    vf_bottom = ""
                    if bottom_esc:
                        vf_bottom = (
                            f"drawtext=text='{bottom_esc}'{font_opt}:"
                            f"x=(w-text_w)/2:y=h-text_h-{int(c['margin_bottom'])}:"
                            f"fontsize=h*{float(c['fs_bottom'])}:"
                            f"fontcolor=white:box=1:boxcolor=black@{box_opacity}:boxborderw=10"
                        )
                    if vf_top and vf_bottom:
                        vf = f"{vf_top},{vf_bottom}"
                    elif vf_top:
                        vf = vf_top
                    elif vf_bottom:
                        vf = vf_bottom
                    else:
                        vf = "null"

                    out_i = tmpdir / f"part_{idx:03d}.mp4"
                    cmd = [
                        get_ffmpeg_exe(), "-y",
                        "-i", str(in_path),
                        "-vf", vf,
                        "-c:v", "libx264",
                        "-crf", str(crf),
                        "-preset", preset,
                        "-c:a", "aac",
                        "-movflags", "+faststart",
                        str(out_i)
                    ]
                    ok, log = run_ffmpeg(cmd)
                    if not ok:
                        st.error(f"クリップ {idx+1} の処理に失敗しました。ログ:\n\n{log}")
                        st.stop()
                    parts.append(out_i)

                # Concat
                listfile = tmpdir / "concat.txt"
                # 置き換え後（安全）
                with open(listfile, "w", encoding="utf-8") as f:
                    for p in parts:
                        sp = str(p)
                        # ffmpeg concat 用の単一引用符エスケープ
                        sp_escaped = sp.replace("'", "'\\''")
                        f.write(f"file '{sp_escaped}'\n")



                out_path = tmpdir / (output_name or "output_joined.mp4")
                cmd_concat = [
                    get_ffmpeg_exe(), "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(listfile),
                    "-c", "copy",
                    str(out_path)
                ]
                ok, log = run_ffmpeg(cmd_concat)
                if not ok:
                    st.error(f"結合に失敗しました。ログ:\n\n{log}")
                    st.stop()

                # Return bytes for download
                with open(out_path, "rb") as f:
                    data = f.read()
                st.success("完了しました。下のボタンからダウンロードできます。")
                st.download_button("📥 ダウンロード", data=data, file_name=Path(output_name).name or "output_joined.mp4", mime="video/mp4")
