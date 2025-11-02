# -*- coding: utf-8 -*-
import streamlit as st
import os, io, tempfile, shutil, subprocess
from pathlib import Path
from typing import List, Tuple, Optional

# --- FFmpeg path via imageio-ffmpeg ---
def get_ffmpeg_exe() -> str:
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

import imageio_ffmpeg

st.set_page_config(page_title="動画結合＋二段字幕（Streamlit）", layout="wide")
st.title("動画結合＋二段字幕（上：共通 / 下：クリップ別）")

st.markdown("""
**手順**
1. 左のサイドバーで上部字幕・出力設定・プレビュー設定を入力  
2. 下で動画をまとめて選択し、順序と各クリップ下部字幕を編集  
3. 「🔎 結合プレビュー」を押すと、**結合後の一本**で先頭N秒を表示  
4. 問題なければ「🎬 結合して書き出す」
""")

# ---------------- Utils ----------------
def has_ffmpeg() -> bool:
    try:
        ff = get_ffmpeg_exe()
        subprocess.run([ff, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        return True
    except Exception:
        return False

def ff_esc_basic(text: str) -> str:
    if text is None:
        return ""
    return text.replace("\\", r"\\")

def run_ffmpeg(cmd: List[str]) -> Tuple[bool, str]:
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        logs = []
        for line in proc.stdout:
            logs.append(line)
        proc.wait()
        ok = (proc.returncode == 0)
        return ok, "".join(logs)
    except Exception as e:
        return False, f"Exception: {e}"

# ★ 同梱フォント探索関数を追加 ----------------
def find_bundled_font() -> Optional[Path]:
    """
    リポジトリ同梱フォントを上位ディレクトリへ遡って探索。
    見つかれば Path を返す。無ければ None。
    """
    try:
        here = Path(__file__).resolve()
        candidate_relpaths = [
            Path("assets/fonts/LanobePOPv2/LightNovelPOPv2.otf"),
            Path("assets/fonts/NotoSansCJKjp/NotoSansCJKjp-Regular.otf"),
            Path("assets/fonts/NotoSansJP/NotoSansJP-Regular.ttf"),
        ]
        for up in [here, *list(here.parents)]:
            base = up.parent if up.is_file() else up
            for rel in candidate_relpaths:
                cand = base / rel
                if cand.exists():
                    return cand
    except Exception:
        pass
    return None

# ---------------- Sidebar ----------------
st.sidebar.header("共通設定（上部字幕 & 書き出し）")
global_top_text = st.sidebar.text_area("上部字幕（全クリップ共通）", value="", height=80, help="空欄で上部字幕なし（複数行OK）")
fs_top = st.sidebar.number_input("上部字幕フォントサイズ（映像高さ×）", value=0.06, step=0.01, min_value=0.01, max_value=0.5)
fs_bottom_default = st.sidebar.number_input("下部字幕フォントサイズ（既定・映像高さ×）", value=0.06, step=0.01, min_value=0.01, max_value=0.5)
margin_top = st.sidebar.number_input("上部の余白(px)", value=40, step=2, min_value=0)
margin_bottom_default = st.sidebar.number_input("下部の余白（既定・px）", value=40, step=2, min_value=0)
box_opacity = st.sidebar.slider("字幕背景の不透明度", 0.0, 1.0, 0.55, 0.05)

st.sidebar.divider()
st.sidebar.subheader("本番エンコード")
crf = st.sidebar.number_input("CRF（画質：16-23推奨）", value=18, step=1, min_value=12, max_value=30)
preset = st.sidebar.selectbox("preset", ["ultrafast","superfast","veryfast","faster","fast","medium","slow","slower","veryslow"], index=5)
output_name = st.sidebar.text_input("出力ファイル名", value="output_joined.mp4")

# 日本語フォント設定
font_file = st.sidebar.file_uploader(
    "（推奨）日本語フォントを指定（TTF/OTF）",
    type=["ttf", "otf"],
    accept_multiple_files=False,
    help="Noto Sans/Source Han など"
)
system_font_name = st.sidebar.text_input(
    "（任意）システムのフォント名（fontconfig）",
    value="",
    help="例: 'Noto Sans CJK JP', 'Source Han Sans JP'（サーバにインストール必須）"
)

st.sidebar.divider()
st.sidebar.subheader("プレビュー設定")
preview_seconds_total = st.sidebar.number_input("プレビュー秒数（結合後の先頭N秒）", value=12, min_value=3, max_value=120, step=1)
preview_downscale = st.sidebar.checkbox("解像度縮小（縦480px）", value=True)
preview_fast_encode = st.sidebar.checkbox("高速エンコード（CRF=28 / ultrafast）", value=True)

# ---------------- File Upload ----------------
st.subheader("動画と下部字幕の入力")
uploads = st.file_uploader("動画ファイルを複数選択", type=["mp4","mov","mkv","avi","m4v","webm"], accept_multiple_files=True)

if "clips" not in st.session_state:
    st.session_state["clips"] = []

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
    st.caption("順序・字幕編集後にプレビュー／書き出しを実行してください。")
    cols = st.columns([3,1,3,1,1])
    with cols[0]: st.markdown("**ファイル名**")
    with cols[1]: st.markdown("**順序**")
    with cols[2]: st.markdown("**下部字幕**")
    with cols[3]: st.markdown("**fs**")
    with cols[4]: st.markdown("**余白**")

    for i, c in enumerate(clips):
        cols = st.columns([3,1,3,1,1])
        with cols[0]: st.text(c["name"])
        with cols[1]: c["order"] = st.number_input(f"order_{i}", value=int(c["order"]), min_value=1, step=1)
        with cols[2]: c["bottom"] = st.text_input(f"bottom_{i}", value=c["bottom"])
        with cols[3]: c["fs_bottom"] = st.number_input(f"fsb_{i}", value=float(c["fs_bottom"]), min_value=0.01, max_value=0.5, step=0.01)
        with cols[4]: c["margin_bottom"] = st.number_input(f"mb_{i}", value=int(c["margin_bottom"]), min_value=0, step=2)
else:
    st.info("動画を選択してください。")

# ---------------- Drawtext Builder ----------------
def write_utf8_text(path: Path, text: str):
    path.write_text(text or "", encoding="utf-8", newline="\n")

def build_drawtexts_via_textfiles(
    workdir: Path,
    top_text: str,
    fs_top_val: float,
    bottom_text: str,
    fs_bottom_val: float,
    margin_top_px: int,
    margin_bottom_px: int,
    box_alpha: float,
    font_path: Optional[Path],
    font_name: Optional[str]
) -> str:
    # フォント解決：アップロード → システム名 → 同梱フォント
    if font_path and font_path.exists():
        font_opt = f":fontfile='{font_path.as_posix()}'"
    elif font_name and font_name.strip():
        font_opt = f":font='{font_name.strip()}'"
    else:
        bundled = find_bundled_font()
        if bundled:
            font_opt = f":fontfile='{bundled.as_posix()}'"
        else:
            font_opt = ""

    filters = []
    if top_text:
        for i, line in enumerate(top_text.split("\n")):
            tfile = workdir / f"top_{i}.txt"
            write_utf8_text(tfile, ff_esc_basic(line))
            y = f"{margin_top_px}+{i}*(h*{fs_top_val}*1.25)"
            filters.append(
                f"drawtext=textfile='{tfile.as_posix()}'{font_opt}:"
                f"x=(w-text_w)/2:y={y}:fontsize=h*{fs_top_val}:"
                f"fontcolor=white:box=1:boxcolor=black@{box_alpha}:boxborderw=10:"
                f"fix_bounds=1:text_shaping=1"
            )
    if bottom_text:
        lines = bottom_text.split("\n")
        N = len(lines)
        for i, line in enumerate(lines):
            tfile = workdir / f"bottom_{i}.txt"
            write_utf8_text(tfile, ff_esc_basic(line))
            y = f"h-( {N}-{i} )*(h*{fs_bottom_val}*1.25)-{margin_bottom_px}"
            filters.append(
                f"drawtext=textfile='{tfile.as_posix()}'{font_opt}:"
                f"x=(w-text_w)/2:y={y}:fontsize=h*{fs_bottom_val}:"
                f"fontcolor=white:box=1:boxcolor=black@{box_alpha}:boxborderw=10:"
                f"fix_bounds=1:text_shaping=1"
            )
    return ",".join(filters) if filters else "null"


# ---------------- Preview (concat → trim) ----------------
preview = st.button("🔎 結合プレビュー（先頭N秒）", use_container_width=True)

if preview:
    if not has_ffmpeg():
        st.error("FFmpeg が見つかりません。PATH を確認してください。")
    elif not clips:
        st.warning("動画が選択されていません。")
    else:
        clips_sorted = sorted(clips, key=lambda x: x["order"])
        with st.spinner("プレビュー生成中..."):
            with tempfile.TemporaryDirectory(prefix="st_preview_concat_") as tmpd:
                tmpdir = Path(tmpd)
                # フォントの保存（アップロードされた場合）
                font_path = None
                if font_file is not None:
                    font_path = tmpdir / font_file.name
                    font_path.write_bytes(font_file.getvalue())

                parts = []
                # 1) 各クリップに字幕焼き込み（低解像度&高速設定）
                for idx, c in enumerate(clips_sorted):
                    in_path = tmpdir / f"in_prev_{idx:03d}{Path(c['name']).suffix}"
                    in_path.write_bytes(c["data"])

                    # 行ごとtextfile方式でフィルタ作成（★ font_name を渡す）
                    line_dir = tmpdir / f"lines_{idx:03d}"
                    line_dir.mkdir(parents=True, exist_ok=True)
                    vf_core = build_drawtexts_via_textfiles(
                        workdir=line_dir,
                        top_text=global_top_text,
                        fs_top_val=fs_top,
                        bottom_text=(c["bottom"] or ""),
                        fs_bottom_val=float(c["fs_bottom"]),
                        margin_top_px=int(margin_top),
                        margin_bottom_px=int(c["margin_bottom"]),
                        box_alpha=box_opacity,
                        font_path=font_path,
                        font_name=system_font_name  # ★ 追加
                    )

                    # 縮小（任意）
                    scale_filter = "scale=-2:480" if preview_downscale else None
                    vf_full = vf_core if vf_core != "null" else (scale_filter or "null")
                    if vf_core != "null" and scale_filter:
                        vf_full = vf_core + "," + scale_filter

                    pv_crf = 28 if preview_fast_encode else max(20, min(30, crf))
                    pv_preset = "ultrafast" if preview_fast_encode else preset

                    out_i = tmpdir / f"part_prev_{idx:03d}.mp4"
                    cmd = [
                        get_ffmpeg_exe(), "-y",
                        "-i", str(in_path),
                        "-vf", vf_full,
                        "-c:v", "libx264", "-crf", str(pv_crf), "-preset", pv_preset,
                        "-c:a", "aac",
                        "-movflags", "+faststart",
                        str(out_i)
                    ]
                    ok, log = run_ffmpeg(cmd)
                    if not ok:
                        st.error(f"プレビュー用エンコードに失敗しました（{c['name']}）。\n\n{log}")
                        st.stop()
                    parts.append(out_i)

                # 2) 連結（concat demuxer）
                listfile = tmpdir / "concat_prev.txt"
                with listfile.open("w", encoding="utf-8") as f:
                    for p in parts:
                        sp = str(p).replace("'", "'\\''")
                        f.write(f"file '{sp}'\n")

                concat_all = tmpdir / "preview_all.mp4"
                ok, log = run_ffmpeg([
                    get_ffmpeg_exe(), "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(listfile),
                    "-c", "copy",
                    str(concat_all)
                ])
                if not ok:
                    st.error(f"プレビューの連結に失敗しました。\n\n{log}")
                    st.stop()

                # 3) 先頭N秒にトリム
                preview_out = tmpdir / "preview_head.mp4"
                ok, log = run_ffmpeg([
                    get_ffmpeg_exe(), "-y",
                    "-ss", "0", "-t", str(int(preview_seconds_total)),
                    "-i", str(concat_all),
                    "-c", "copy",
                    str(preview_out)
                ])
                if not ok:
                    # stream copy が合わない場合の超高速再エンコード
                    ok2, log2 = run_ffmpeg([
                        get_ffmpeg_exe(), "-y",
                        "-ss", "0", "-t", str(int(preview_seconds_total)),
                        "-i", str(concat_all),
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
                        "-c:a", "aac",
                        "-movflags", "+faststart",
                        str(preview_out)
                    ])
                    if not ok2:
                        st.error(f"プレビューのトリムに失敗しました。\n\n{log}\n{log2}")
                        st.stop()

                st.success(f"結合後の先頭 {preview_seconds_total} 秒プレビュー")
                st.video(str(preview_out))

# ---------------- Final export (full quality) ----------------
run = st.button("🎬 結合して書き出す", use_container_width=True)

if run:
    if not has_ffmpeg():
        st.error("FFmpeg が見つかりません。PATH を確認してください。")
    elif not clips:
        st.warning("動画が選択されていません。")
    else:
        clips_sorted = sorted(clips, key=lambda x: x["order"])
        with st.spinner("書き出し中...（時間がかかる場合があります）"):
            with tempfile.TemporaryDirectory(prefix="st_join_export_") as tmpd:
                tmpdir = Path(tmpd)

                font_path = None
                if font_file is not None:
                    font_path = tmpdir / font_file.name
                    font_path.write_bytes(font_file.getvalue())

                parts = []
                # 各クリップを本番設定で焼き込み
                for idx, c in enumerate(clips_sorted):
                    in_path = tmpdir / f"in_{idx:03d}{Path(c['name']).suffix}"
                    in_path.write_bytes(c["data"])

                    line_dir = tmpdir / f"lines_export_{idx:03d}"
                    line_dir.mkdir(parents=True, exist_ok=True)
                    vf = build_drawtexts_via_textfiles(
                        workdir=line_dir,
                        top_text=global_top_text,
                        fs_top_val=fs_top,
                        bottom_text=(c["bottom"] or ""),
                        fs_bottom_val=float(c["fs_bottom"]),
                        margin_top_px=int(margin_top),
                        margin_bottom_px=int(c["margin_bottom"]),
                        box_alpha=box_opacity,
                        font_path=font_path,
                        font_name=system_font_name  # ★ 追加
                    )

                    out_i = tmpdir / f"part_{idx:03d}.mp4"
                    cmd = [
                        get_ffmpeg_exe(), "-y",
                        "-i", str(in_path),
                        "-vf", vf,
                        "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
                        "-c:a", "aac",
                        "-movflags", "+faststart",
                        str(out_i)
                    ]
                    ok, log = run_ffmpeg(cmd)
                    if not ok:
                        st.error(f"クリップ {idx+1} の処理に失敗しました。\n\n{log}")
                        st.stop()
                    parts.append(out_i)

                listfile = tmpdir / "concat.txt"
                with listfile.open("w", encoding="utf-8") as f:
                    for p in parts:
                        sp = str(p).replace("'", "'\\''")
                        f.write(f"file '{sp}'\n")

                out_path = tmpdir / (output_name or "output_joined.mp4")
                ok, log = run_ffmpeg([
                    get_ffmpeg_exe(), "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(listfile),
                    "-c", "copy",
                    str(out_path)
                ])
                if not ok:
                    st.error(f"結合に失敗しました。\n\n{log}")
                    st.stop()

                data = out_path.read_bytes()
                st.success("完了しました。下のボタンからダウンロードできます。")
                st.download_button("📥 ダウンロード", data=data,
                                   file_name=Path(output_name).name or "output_joined.mp4",
                                   mime="video/mp4")
