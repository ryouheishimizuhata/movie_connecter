
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

st.set_page_config(page_title="動画結合＋二段字幕（Streamlit）", layout="wide")

st.title("動画結合＋二段字幕（上：共通 / 下：クリップ別）")

st.markdown("""
**手順**
1. 左のサイドバーで共通（上部）字幕や書き出し設定を入力  
2. 下で動画をまとめて選択（複数可）し、順序と各クリップ下部字幕を入力（**下部は複数行OK**）  
3. 「▶ プレビューを生成」でレイアウト確認 → 問題なければ「🎬 結合して書き出す」  
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
    """Escape for ffmpeg drawtext. Keep explicit \\n for line breaks."""
    if text is None:
        return ""
    t = text.replace("\\", r"\\\\")
    t = t.replace(":", r"\:")
    t = t.replace("'", r"\'")
    t = t.replace("\n", r"\n")
    return t

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

# --------------- Sidebar Settings ---------------
st.sidebar.header("共通設定（上部字幕 & 書き出し）")
global_top_text = st.sidebar.text_area("上部字幕（全クリップ共通）", value="", height=80, help="空欄で上部字幕なし。改行可。")
fs_top = st.sidebar.number_input("上部字幕フォントサイズ（映像高さ×）", value=0.04, step=0.01, min_value=0.01, max_value=0.5)
fs_bottom_default = st.sidebar.number_input("下部字幕フォントサイズ（既定・映像高さ×）", value=0.06, step=0.01, min_value=0.01, max_value=0.5)
margin_top = st.sidebar.number_input("上部の余白(px)", value=300, step=2, min_value=0)
margin_bottom_default = st.sidebar.number_input("下部の余白（既定・px）", value=500, step=2, min_value=0)
box_opacity = st.sidebar.slider("字幕背景の不透明度", 0.0, 1.0, 0.55, 0.05)
crf = st.sidebar.number_input("CRF（画質：16-23推奨）", value=18, step=1, min_value=12, max_value=30)
preset = st.sidebar.selectbox("preset", ["ultrafast","superfast","veryfast","faster","fast","medium","slow","slower","veryslow"], index=5)
output_name = st.sidebar.text_input("出力ファイル名", value="output_joined.mp4")
font_file = st.sidebar.file_uploader("（任意）TrueType/OpenTypeフォントを指定", type=["ttf","otf"], accept_multiple_files=False, help="日本語字幕でフォントを指定したい場合に使用")
font_name = st.sidebar.text_input("（任意）フォント名（例: Noto Sans CJK JP / ラノベPOP）", value="ラノベPOP")

st.sidebar.header("縦動画キャンバス設定")
use_vertical_canvas = st.sidebar.checkbox("縦1080×1920のキャンバスに固定する", value=True)
scale_ratio = st.sidebar.number_input("元動画の縮小率（例: 0.32）", value=1.00, step=0.01, min_value=0.05, max_value=2.0)
offset_up = st.sidebar.number_input("中央から上方向オフセット（px）", value=120, step=10, min_value=0, help="数値が大きいほど上に寄せます")

st.sidebar.header("プレビュー設定")
preview_seconds = st.sidebar.number_input("各クリップあたりのプレビュー秒数", value=3.0, step=0.5, min_value=0.5, max_value=30.0)
preview_half_res = st.sidebar.checkbox("プレビューを半分解像度(540×960)で生成", value=True)

st.sidebar.info("⚠️ ローカル/サーバ実行を想定。stlite（ブラウザのみ）では FFmpeg は動きません。")

# --------------- Inputs: videos ---------------
st.subheader("動画と下部字幕の入力")
uploads = st.file_uploader("動画ファイルを複数選択（順序は後で変更可）", type=["mp4","mov","mkv","avi","m4v","webm"], accept_multiple_files=True)

if "clips" not in st.session_state:
    st.session_state["clips"] = []  # List[dict]
    # dict keys: {"name","data","order","bottom","fs_bottom","margin_bottom"}

def rebuild_from_uploads():
    existing = st.session_state["clips"]
    new_items = []
    existing_keys = {(c["name"], len(c["data"])) for c in existing}
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
    st.caption("順序・各字幕を編集してから下のボタンでプレビュー／書き出ししてください。")
    cols = st.columns([3,1,3,1,1])
    with cols[0]: st.markdown("**ファイル名**")
    with cols[1]: st.markdown("**順序**")
    with cols[2]: st.markdown("**下部字幕（複数行OK）**")
    with cols[3]: st.markdown("**fs**")
    with cols[4]: st.markdown("**余白**")

    for i, c in enumerate(clips):
        cols = st.columns([3,1,3,1,1])
        with cols[0]:
            st.text(c["name"])
        with cols[1]:
            c["order"] = st.number_input(f"order_{i}", value=int(c["order"]), min_value=1, step=1, key=f"ord_{i}")
        with cols[2]:
            c["bottom"] = st.text_area(f"bottom_{i}", value=c["bottom"], key=f"bot_{i}", height=90, help="改行可（そのまま反映されます）")
        with cols[3]:
            c["fs_bottom"] = st.number_input(f"fsb_{i}", value=float(c["fs_bottom"]), min_value=0.01, max_value=0.5, step=0.01, key=f"fsbkey_{i}")
        with cols[4]:
            c["margin_bottom"] = st.number_input(f"mb_{i}", value=int(c["margin_bottom"]), min_value=0, step=2, key=f"mbkey_{i}")
else:
    st.info("動画を選択してください。")

from pathlib import Path

def _escape_single_quotes(p: str) -> str:
    # concat.txt と同様、ffmpeg 引数での単一引用符エスケープ
    return p.replace("'", "'\\''")

def _write_textfile(tmpdir: Path, name: str, text: str) -> Path:
    path = tmpdir / name
    # LFで保存（UTF-8）。Windows/ macOS どちらでもOK
    path.write_text(text or "", encoding="utf-8", newline="\n")
    return path

# --------------- Shared building blocks ---------------
def build_font_opt(tmpdir: Path) -> str:
    \"\"\"Choose font in the following order:
    1) Uploaded font file (sidebar-uploader)
    2) Explicit font name (sidebar text)
    3) Bundled asset: assets/fonts/LightNovelPOPv2.otf (search upward)
    4) Default (no font option)
    \"\"\"
    # 1) Uploaded font has highest priority (exact file path)
    if 'font_file' in globals() and font_file is not None:
        p = tmpdir / font_file.name
        with open(p, "wb") as f:
            f.write(font_file.getvalue())
        return f":fontfile='{p.as_posix()}'"

    # 2) Named font (system-available name)
    if 'font_name' in globals() and isinstance(font_name, str) and font_name.strip():
        return f":font='{font_name.strip()}'"

    # 3) Bundled asset: search assets/fonts/LightNovelPOPv2.otf upward from current file
    try:
        here = Path(__file__).resolve()
        for up in [here, *list(here.parents)]:
            cand = up.parent / "assets" / "fonts" / "LightNovelPOPv2.otf"
            if cand.exists():
                return f":fontfile='{cand.as_posix()}'"
    except Exception:
        pass

    # 4) Default
    return ""  # default

def build_vf_chain(top_text: str, bottom_text: str, margin_bottom: int, fs_bottom: float, margin_top_px: int, tmpdir: Path) -> str:
    vf_elems = []
    # 1) SARを正規化
    vf_elems.append("setsar=1")
    # 2) 縦横比維持で短辺合わせ（1080×1920の枠内に収める）
    vf_elems.append(
        "scale=w=trunc(iw*min(1080/iw\\,1920/ih)/2)*2:"
        "h=trunc(ih*min(1080/iw\\,1920/ih)/2)*2"
    )
    # 3) 出力色空間（H.264の互換性向上）
    vf_elems.append("format=yuv420p")
    # 4) キャンバスにパディング（中央寄せ。上寄せしたいなら y を調整）
    vf_elems.append("pad=1080:1920:(1080-iw)/2:(1920-ih)/2:black")
    # 5) 以降に drawtext（字幕）
    font_opt = build_font_opt(tmpdir)

    # 上部字幕（各行を個別に中央揃え）
    if top_text:
        lines = top_text.splitlines()  # ここで複数行に分割
        line_spacing = 1.2             # 行間（フォントサイズ比）。必要に応じて調整
        for i, line in enumerate(lines):
            te_line = ff_esc(line)
            # y = 上余白 + 行番号 * (フォントサイズ×行間)
            y_expr = int(margin_top) + i * int(fs_top * 1000)  # ダミー式（下でhベースに直す例を使用）

            vf_elems.append(
                f"drawtext=text='{te_line}'{font_opt}:"
                f"x=(w-text_w)/2:"
                # h*fs_top*行間×i を使って行送り。整数化不要ならそのまま式でOK。
                f"y={int(margin_top)}+{i}*(h*{fs_top}*{line_spacing}):"
                f"fontsize=h*{fs_top}:"
                f"fontcolor=white:box=1:boxcolor=black@{box_opacity}:boxborderw=10"
            )


    # ▼ 下部字幕：textfile= を使う（複数行OK）
    if bottom_text:
        bottom_path = _write_textfile(tmpdir, "bottom.txt", bottom_text)
        bottom_arg = _escape_single_quotes(bottom_path.as_posix())
        vf_elems.append(
            f"drawtext=textfile='{bottom_arg}'{font_opt}:"
            f"x=(w-text_w)/2:y=h-text_h-{int(margin_bottom)}:"
            f"fontsize=h*{float(fs_bottom)}:fontcolor=white:"
            f"box=1:boxcolor=black@{box_opacity}:boxborderw=10"
        )

    return ",".join(vf_elems)

# --------------- Buttons ---------------
col_run1, col_run2 = st.columns(2)
preview_btn = col_run1.button("▶ プレビューを生成（結合）", use_container_width=True)
export_btn  = col_run2.button("🎬 結合して書き出す", use_container_width=True)

# --------------- Preview ---------------
if preview_btn:
    if not has_ffmpeg():
        st.error("FFmpeg が見つかりません。ローカルにインストールし、PATH を通してください。")
    elif not clips:
        st.warning("動画が選択されていません。")
    else:
        clips_sorted = sorted(clips, key=lambda x: x["order"])
        with st.spinner("プレビューを生成中..."):
            with tempfile.TemporaryDirectory(prefix="st_join_preview_") as tmpd:
                tmpdir = Path(tmpd)
                parts = []
                for idx, c in enumerate(clips_sorted):
                    in_path = tmpdir / f"in_{idx:03d}{Path(c['name']).suffix}"
                    with open(in_path, "wb") as f:
                        f.write(c["data"])
                    vf = build_vf_chain(global_top_text, c["bottom"] or "", c["margin_bottom"], c["fs_bottom"], margin_top, tmpdir)
                    out_i = tmpdir / f"part_prev_{idx:03d}.mp4"
                    # プレビューは解像度半分＆高CRFで軽量化
                    vf_prev = vf
                    if preview_half_res and use_vertical_canvas:
                        vf_prev = vf + ",scale=540:960"
                    cmd = [
                        get_ffmpeg_exe(), "-y",
                        "-i", str(in_path),
                        "-t", str(preview_seconds),
                        "-vf", vf_prev,
                        "-c:v", "libx264",
                        "-crf", "28",
                        "-preset", "veryfast",
                        "-c:a", "aac",
                        "-movflags", "+faststart",
                        str(out_i)
                    ]
                    ok, log = run_ffmpeg(cmd)
                    if not ok:
                        st.error(f"プレビュー用クリップ {idx+1} の処理に失敗しました。ログ:\n\n{log}")
                        st.stop()
                    parts.append(out_i)

                # concat previews
                listfile = tmpdir / "concat_prev.txt"
                with open(listfile, "w", encoding="utf-8") as f:
                    for p in parts:
                        sp = str(p).replace("'", "'\\''")
                        f.write(f"file '{sp}'\n")

                out_prev = tmpdir / "preview_joined.mp4"
                cmd_concat = [
                    get_ffmpeg_exe(), "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(listfile),
                    "-c", "copy",
                    str(out_prev)
                ]
                ok, log = run_ffmpeg(cmd_concat)
                if not ok:
                    st.error(f"プレビューの結合に失敗しました。ログ:\n\n{log}")
                    st.stop()

                with open(out_prev, "rb") as f:
                    prev_bytes = f.read()
                st.success("プレビューの準備ができました。下で再生できます。")
                st.video(prev_bytes)

# --------------- Export ---------------
if export_btn:
    if not has_ffmpeg():
        st.error("FFmpeg が見つかりません。ローカルにインストールし、PATH を通してください。")
    elif not clips:
        st.warning("動画が選択されていません。")
    else:
        clips_sorted = sorted(clips, key=lambda x: x["order"])
        with st.spinner("書き出し中...（時間がかかる場合があります）"):
            with tempfile.TemporaryDirectory(prefix="st_join_subs_") as tmpd:
                tmpdir = Path(tmpd)
                parts = []
                for idx, c in enumerate(clips_sorted):
                    in_path = tmpdir / f"in_{idx:03d}{Path(c['name']).suffix}"
                    with open(in_path, "wb") as f:
                        f.write(c["data"])
                    vf = build_vf_chain(global_top_text, c["bottom"] or "", c["margin_bottom"], c["fs_bottom"], margin_top, tmpdir)
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

                listfile = tmpdir / "concat.txt"
                with open(listfile, "w", encoding="utf-8") as f:
                    for p in parts:
                        sp = str(p).replace("'", "'\\''")
                        f.write(f"file '{sp}'\n")

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

                with open(out_path, "rb") as f:
                    data = f.read()
                st.success("完了しました。下のボタンからダウンロードできます。")
                st.download_button("📥 ダウンロード", data=data, file_name=Path(output_name).name or "output_joined.mp4", mime="video/mp4")
