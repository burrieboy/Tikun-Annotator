import streamlit as st
import fitz
import io
import os
import re
import urllib.request

# =========================================================================
# SELF-HEALING & ABSOLUTE FONT PATH RESOLUTION
# =========================================================================
font_file = os.path.abspath("Alef-Regular.ttf")

def is_valid_ttf(filepath):
    if not os.path.exists(filepath):
        return False
    if os.path.getsize(filepath) < 50000:
        return False
    try:
        with open(filepath, 'rb') as f:
            sig = f.read(4)
            return sig in (b'\x00\x01\x00\x00', b'OTTO')
    except Exception:
        return False

if os.path.exists(font_file) and not is_valid_ttf(font_file):
    try:
        os.remove(font_file)
    except Exception:
        pass

if not os.path.exists(font_file):
    urls = [
        "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/alef/Alef-Regular.ttf",
        "https://github.com/google/fonts/raw/main/ofl/alef/Alef-Regular.ttf"
    ]
    success = False
    for url in urls:
        try:
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                data = response.read()
                with open(font_file, 'wb') as out_file:
                    out_file.write(data)
            if is_valid_ttf(font_file):
                success = True
                break
        except Exception as e:
            if os.path.exists(font_file):
                try:
                    os.remove(font_file)
                except Exception:
                    pass
    if not success:
        raise RuntimeError("Could not obtain a Hebrew font.")

# =========================================================================
# YOUR MAGIC NUMBERS (Tight & Clean Spacing)
# =========================================================================
SAFETY_GAP_FROM_TEXT = 8    # Distance between the longest Hebrew line and the Scores
SCORE_TO_NUM_GAP     = 15   # Distance between the Scores and the Line Numbers
NUM_TO_CATCH_GAP     = 12   # Distance between the Line Numbers and the Catchwords

# =========================================================================
# MARGIN CROP CONFIGURATION (Fallback Defaults)
# =========================================================================
TOP_CROP_PERCENT    = 0.11  
BOTTOM_CROP_PERCENT = 0.06  
LEFT_CROP_PERCENT   = 0.04  
RIGHT_CROP_PERCENT  = 0.04  

# =========================================================================
# LINE NUMBER CONFIGURATION
# =========================================================================
NUMBER_FONT_SIZE    = 9        
NUMBER_COLOR        = (0, 0, 0) 

stretchable_letters = {'ד', 'ר', 'ק', 'ת', 'ל', 'ה'}

# =========================================================================
# UTILITY FUNCTIONS
# =========================================================================
def strip_nikud(text):
    """Removes all Hebrew vowels (nikud) and cantillation marks (taamim)."""
    return re.sub(r'[\u0591-\u05c7]', '', text)

def int_to_hebrew(n):
    """Converts an integer to Hebrew Gematria (1-59) with standard exceptions."""
    if n <= 0:
        return ""
    if n == 15:
        return "טו"
    if n == 16:
        return "טז"
    
    tens = {10: 'י', 20: 'כ', 30: 'ל', 40: 'מ', 50: 'נ'}
    ones = {1: 'א', 2: 'ב', 3: 'ג', 4: 'ד', 5: 'ה', 6: 'ו', 7: 'ז', 8: 'ח', 9: 'ט'}
    
    result = ""
    t_val = (n // 10) * 10
    if t_val in tens:
        result += tens[t_val]
    o_val = n % 10
    if o_val in ones:
        result += ones[o_val]
    return result

def fix_rtl(text):
    return text[::-1]

def flag_fillers_in_line_chars(chars):
    filler_letters = {'א', 'ש', 'ר', 'י'}
    n = len(chars)
    i = 0
    while i < n:
        c_text = chars[i]["c"]
        base = strip_nikud(c_text).strip()
        base_clean = re.sub(r'[^\u05d0-\u05ea]', '', base)
        
        if base_clean and all(char in filler_letters for char in base_clean):
            start = i
            while i < n:
                next_c_text = chars[i]["c"]
                next_base = strip_nikud(next_c_text).strip()
                next_base_clean = re.sub(r'[^\u05d0-\u05ea]', '', next_base)
                
                if next_base_clean and any(char not in filler_letters for char in next_base_clean):
                    break
                i += 1
            end = i
            
            run_chars = [chars[j] for j in range(start, end) if chars[j]["c"].strip()]
            run_text = "".join([re.sub(r'[^\u05d0-\u05ea]', '', strip_nikud(c["c"]).strip()) for c in run_chars])
            
            is_run_filler = False
            if len(run_text) >= 5:
                is_run_filler = True
            elif run_text in {"אשרי", "ירשא", "אשריי", "יירשא"}:
                is_run_filler = True
                
            if is_run_filler:
                for j in range(start, end):
                    chars[j]["is_biblical"] = False
        else:
            i += 1

# =========================================================================
# THE MAIN PROCESSING FUNCTION
# =========================================================================
def generate_annotated_tikun_streamlit(uploaded_file, output_buffer, score_x_adj, arrow_y_adj):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    total_pages = len(doc)
    
    # Global calibration
    bucketed_sizes = {}
    pages_to_scan = min(20, total_pages)
    
    for p_num in range(pages_to_scan):
        p = doc[p_num]
        p_data = p.get_text("rawdict")
        for block in p_data.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        sz = span["size"]
                        if 8.0 <= sz <= 30.0:
                            bucket = round(sz)
                            bucketed_sizes[bucket] = bucketed_sizes.get(bucket, 0) + len(span["chars"])
                        
    if not bucketed_sizes:
        dominant_bucket = 16
    else:
        dominant_bucket = max(bucketed_sizes, key=bucketed_sizes.get)
            
    min_size_limit = dominant_bucket - 1.2
    max_size_limit = dominant_bucket + 1.8

    for page_num in range(total_pages):
        page = doc[page_num]
        page.insert_font(fontname="alef", fontfile=font_file)
        page_data = page.get_text("rawdict")
        
        page_width = page.rect.width
        page_height = page.rect.height
        
        left_limit   = page_width * LEFT_CROP_PERCENT    
        right_limit  = page_width * (1.0 - RIGHT_CROP_PERCENT)    
        top_limit    = page_height * TOP_CROP_PERCENT   
        bottom_limit = page_height * (1.0 - BOTTOM_CROP_PERCENT)   

        header_y_boundary = None
        for block in page_data.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    line_text = ""
                    for span in line["spans"]:
                        if "chars" in span:
                            line_text += "".join([c["c"] for c in span["chars"]])
                    
                    has_keyword = "רוחב שורה" in line_text or "הרוש בחור" in line_text
                    has_dots = len(re.findall(r'[\.\-\_~*·•]{5,}', line_text)) > 0
                    
                    if has_keyword or has_dots:
                        lx0, ly0, lx1, ly1 = line["bbox"]
                        current_boundary = ly1 + 2  
                        if header_y_boundary is None or current_boundary > header_y_boundary:
                            header_y_boundary = current_boundary
                            
        page_top_limit = max(top_limit, header_y_boundary) if header_y_boundary is not None else top_limit
        
        redactions_to_apply = []
        digit_spans = []
        
        for block in page_data.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        span_text = "".join([c["c"] for c in span["chars"]]).strip()
                        match = re.search(r'\b\d+\b', span_text)
                        if match:
                            num_val = int(match.group(0))
                            if 1 <= num_val <= 50:
                                s_x0, s_y0, s_x1, s_y1 = span["bbox"]
                                digit_spans.append({
                                    "text": match.group(0),
                                    "bbox": fitz.Rect(span["bbox"]),
                                    "center_y": (s_y0 + s_y1) / 2
                                })
        
        raw_lines = []
        for block in page_data.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    line_text = ""
                    all_chars = []
                    line_sizes = []
                    
                    for span in line["spans"]:
                        for char_obj in span["chars"]:
                            line_text += char_obj["c"]
                            all_chars.append(char_obj)
                        line_sizes.append((span["size"], len(span["chars"])))
                    
                    total_chars = sum(count for _, count in line_sizes)
                    if total_chars == 0:
                        continue
                    weighted_size = sum(sz * count for sz, count in line_sizes) / total_chars
                    if not (min_size_limit <= weighted_size <= max_size_limit):
                        continue
                    
                    x0, y0, x1, y1 = line["bbox"]
                    center_x = (x0 + x1) / 2
                    center_y = (y0 + y1) / 2
                    
                    if not (left_limit <= center_x <= right_limit) or not (page_top_limit <= center_y <= bottom_limit):
                        continue
                        
                    cleaned_physical = line_text.strip()
                    if not any('\u0590' <= char <= '\u05fe' for char in cleaned_physical):
                        continue
                        
                    raw_lines.append({
                        "text": line_text,
                        "chars": all_chars,
                        "spans": line["spans"], 
                        "bbox": line["bbox"],
                        "center_y": center_y,
                        "x0": x0
                    })
        
        consolidated_lines = []
        raw_lines.sort(key=lambda l: l["center_y"])
        
        for r_line in raw_lines:
            merged = False
            for c_line in consolidated_lines:
                if abs(r_line["center_y"] - c_line["center_y"]) < 6:
                    c_line["parts"].append(r_line)
                    cx0, cy0, cx1, cy1 = c_line["bbox"]
                    rx0, ry0, rx1, ry1 = r_line["bbox"]
                    c_line["bbox"] = (
                        min(cx0, rx0),
                        min(cy0, ry0),
                        max(cx1, rx1),
                        max(cy1, ry1)
                    )
                    c_line["center_y"] = (c_line["bbox"][1] + c_line["bbox"][3]) / 2
                    merged = True
                    break
            if not merged:
                consolidated_lines.append({
                    "parts": [r_line],
                    "bbox": r_line["bbox"],
                    "center_y": r_line["center_y"]
                })
        
        valid_blocks = []
        for c_line in consolidated_lines:
            all_chars = []
            for part in c_line["parts"]:
                all_chars.extend(part["chars"])
            
            printable_chars = [c for c in all_chars if c["c"].strip()]
            
            if not printable_chars:
                continue
            
            for c in printable_chars:
                c["is_biblical"] = True
                
            flag_fillers_in_line_chars(printable_chars)
            printable_chars.sort(key=lambda c: c["bbox"][0])
            
            biblical_chars = [c for c in printable_chars if c.get("is_biblical", True)]
            
            biblical_word_clusters = []
            current_cluster = []
            for char_obj in biblical_chars:
                if not current_cluster:
                    current_cluster.append(char_obj)
                else:
                    prev_char = current_cluster[-1]
                    gap = char_obj["bbox"][0] - prev_char["bbox"][2]
                    font_size = char_obj.get("size", 12)
                    gap_threshold = max(3.5, font_size * 0.24)
                    
                    if gap > gap_threshold:
                        biblical_word_clusters.append(current_cluster)
                        current_cluster = [char_obj]
                    else:
                        current_cluster.append(char_obj)
            if current_cluster:
                biblical_word_clusters.append(current_cluster)
                
            biblical_words = []
            for cluster in biblical_word_clusters:
                cluster.sort(key=lambda c: c["bbox"][0], reverse=True) 
                word_text = "".join([c["c"] for c in cluster])
                if word_text.strip():
                    biblical_words.append(word_text)
                    
            physical_word_clusters = []
            current_cluster = []
            for char_obj in printable_chars:
                if not current_cluster:
                    current_cluster.append(char_obj)
                else:
                    prev_char = current_cluster[-1]
                    gap = char_obj["bbox"][0] - prev_char["bbox"][2]
                    font_size = char_obj.get("size", 12)
                    gap_threshold = max(3.5, font_size * 0.24)
                    
                    if gap > gap_threshold:
                        physical_word_clusters.append(current_cluster)
                        current_cluster = [char_obj]
                    else:
                        current_cluster.append(char_obj)
            if current_cluster:
                physical_word_clusters.append(current_cluster)
                
            physical_words = []
            for cluster in physical_word_clusters:
                cluster.sort(key=lambda c: c["bbox"][0], reverse=True) 
                word_text = "".join([c["c"] for c in cluster])
                if word_text.strip():
                    physical_words.append(word_text)
            
            cleaned_biblical_words = []
            for w in biblical_words:
                w_clean = re.sub(r'^\d+\s*', '', w).strip()
                w_clean = re.sub(r'[^\u05d0-\u05ea\u0590-\u05c7]', '', w_clean).strip()
                if w_clean:
                    cleaned_biblical_words.append(w_clean)
            
            cleaned_biblical_words_rtl = list(reversed(cleaned_biblical_words))
            cleaned_biblical = " ".join(cleaned_biblical_words_rtl)
            
            cleaned_physical_words = []
            for w in physical_words:
                w_clean = re.sub(r'^\d+\s*', '', w).strip()
                if w_clean:
                    cleaned_physical_words.append(w_clean)
            
            cleaned_physical_words_rtl = list(reversed(cleaned_physical_words))
            cleaned_physical = " ".join(cleaned_physical_words_rtl)
            
            if not cleaned_physical or cleaned_physical.isdigit():
                continue
            
            if len(cleaned_biblical) == 0:
                continue
                
            if len(cleaned_physical.split()) < 2:
                continue
            
            combined_chars = list(printable_chars)
            inline_num_rect = None
            inline_num_str = ""
            
            combined_text = " ".join(physical_words)
            digit_match = re.match(r'^(\s*)(\d+)(\s*)', combined_text)
            if digit_match:
                inline_num_str = digit_match.group(2)
                for char_obj in combined_chars:
                    if char_obj["c"].isdigit():
                        char_obj["is_biblical"] = False
                        if inline_num_rect is None:
                            inline_num_rect = fitz.Rect(char_obj["bbox"])
                        else:
                            inline_num_rect.include_rect(char_obj["bbox"])
            
            for char_obj in combined_chars:
                if not any('\u0590' <= char <= '\u05fe' for char in char_obj["c"]):
                    char_obj["is_biblical"] = False
            
            hebrew_printable_chars = [c for c in combined_chars if any('\u0590' <= char <= '\u05fe' for char in c["c"])]
            hebrew_biblical_chars = [c for c in hebrew_printable_chars if c.get("is_biblical", True)]
            
            hashem_clusters = []
            for cluster in biblical_word_clusters:
                word_text = "".join([c["c"] for c in sorted(cluster, key=lambda c: c["bbox"][0], reverse=True)])
                clean_word = re.sub(r'[^\u05d0-\u05ea]', '', strip_nikud(word_text))
                if clean_word == "יהוה":
                    hashem_clusters.append(cluster)
            
            hashem_char_ids = {id(c) for cluster in hashem_clusters for c in cluster}
            non_hashem_biblical_chars = [c for c in hebrew_biblical_chars if id(c) not in hashem_char_ids]
            
            effective_char_count = len(non_hashem_biblical_chars)
            effective_char_count += 4.0 * len(hashem_clusters)
            
            full_line_raw_text = "".join([re.sub(r'[^\u05d0-\u05ea]', '', strip_nikud(c["c"])) for c in hebrew_printable_chars])
            
            filler_runs = []
            current_run = []
            for c in hebrew_printable_chars:
                if not c.get("is_biblical", True):
                    current_run.append(c)
                else:
                    if current_run:
                        filler_runs.append(current_run)
                        current_run = []
            if current_run:
                filler_runs.append(current_run)
            
            has_triple_ashrei = "אשריאשריאשרי" in full_line_raw_text
            
            if has_triple_ashrei:
                effective_char_count += 48.0
            else:
                for run in filler_runs:
                    effective_char_count += len(run)
            
            valid_blocks.append({
                "physical_text": cleaned_physical,
                "biblical_text": cleaned_biblical,
                "biblical_words_list": cleaned_biblical_words_rtl, 
                "chars": combined_chars,
                "bbox": c_line["bbox"],
                "inline_num_rect": inline_num_rect,
                "inline_num_str": inline_num_str,
                "effective_char_count": effective_char_count
            })
        
        valid_blocks.sort(key=lambda b: b["bbox"][1])
        biblical_lines = valid_blocks
        
        if not biblical_lines:
            continue
            
        for block in biblical_lines:
            x0, y0, x1, y1 = block["bbox"]
            line_center_y = (y0 + y1) / 2
            
            num_str = block["inline_num_str"]
            num_rect = block["inline_num_rect"]
            
            if not num_str and digit_spans:
                best_match = None
                best_dist = 99999
                for span in digit_spans:
                    dist = abs(span["center_y"] - line_center_y)
                    if dist < 20 and dist < best_dist:
                        best_dist = dist
                        best_match = span
                
                if best_match:
                    num_str = best_match["text"]
                    num_rect = best_match["bbox"]
                    digit_spans.remove(best_match)
            
            block["matched_num_str"] = num_str
            block["matched_num_rect"] = num_rect
            
        max_x1 = max(b["bbox"][2] for b in biblical_lines)
        
        SCORE_COL_X     = max_x1 + SAFETY_GAP_FROM_TEXT + score_x_adj
        LINE_NUM_COL_X  = SCORE_COL_X + SCORE_TO_NUM_GAP
        CATCHWORD_COL_X = LINE_NUM_COL_X + NUM_TO_CATCH_GAP

        avg_chars = round(sum(b["effective_char_count"] for b in biblical_lines) / len(biblical_lines))
        prev_first_word = "—"
        
        for block in biblical_lines:
            num_rect = block["matched_num_rect"]
            if num_rect:
                padded_rect = fitz.Rect(num_rect.x0 - 2, num_rect.y0 - 2, num_rect.x1 + 2, num_rect.y1 + 2)
                redactions_to_apply.append(padded_rect)
                
        for rect in redactions_to_apply:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        if redactions_to_apply:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            
        for i, block in enumerate(biblical_lines):
            effective_char_count = block["effective_char_count"]
            biblical_text = block["biblical_text"]
            biblical_words_list = block["biblical_words_list"]
            chars = block["chars"]
            x0, y0, x1, y1 = block["bbox"]
            line_center_y = (y0 + y1) / 2
            
            SCORE_X       = SCORE_COL_X
            LINE_NUMBER_X = LINE_NUM_COL_X
            CATCHWORD_X   = CATCHWORD_COL_X
            
            baseline_y = line_center_y + 3
            
            score_val = avg_chars - effective_char_count
            score_val_rounded = round(score_val)
            if score_val_rounded > 0:
                score_str = f"ח{int_to_hebrew(score_val_rounded)}"
            elif score_val_rounded < 0:
                score_str = f"י{int_to_hebrew(abs(score_val_rounded))}"
            else:
                score_str = "שת"    
                
            catch_word = prev_first_word
            
            if biblical_words_list:
                prev_first_word = biblical_words_list[0]
            else:
                prev_first_word = "—"
            
            page.insert_text(
                fitz.Point(SCORE_X, baseline_y), 
                fix_rtl(score_str), 
                fontsize=10, 
                fontname="alef", 
                fontfile=font_file,
                color=(0, 0, 0),
                overlay=True
            )
            
            page.insert_text(
                fitz.Point(CATCHWORD_X, baseline_y), 
                fix_rtl(catch_word), 
                fontsize=9, 
                fontname="alef", 
                fontfile=font_file,
                color=(0.4, 0.4, 0.4),
                overlay=True
            )
            
            if block["matched_num_str"]:
                page.insert_text(
                    fitz.Point(LINE_NUMBER_X, baseline_y), 
                    block["matched_num_str"], 
                    fontsize=NUMBER_FONT_SIZE, 
                    fontname="alef", 
                    fontfile=font_file,
                    color=NUMBER_COLOR,
                    overlay=True
                )
            
            biblical_chars = [c for c in chars if c.get("is_biblical", True) and c["c"].strip()]
            biblical_chars_sorted = sorted(biblical_chars, key=lambda c: c["bbox"][0])
            
            target_char = None
            for char_obj in biblical_chars_sorted:
                if char_obj["c"] in stretchable_letters:
                    target_char = char_obj
                    break  
            
            if target_char:
                cx0, cy0, cx1, cy1 = target_char["bbox"]
                char_center_x = (cx0 + cx1) / 2
                
                ARROW_DOWNWARD_SHIFT = 10.0 + arrow_y_adj
                arrow_tip_y = cy0 + ARROW_DOWNWARD_SHIFT
                arrow_top_y = arrow_tip_y - 4.5
                
                page.draw_line(
                    fitz.Point(char_center_x, arrow_top_y), 
                    fitz.Point(char_center_x, arrow_tip_y), 
                    color=(0.8, 0.1, 0.1), 
                    width=1
                )
                page.draw_line(
                    fitz.Point(char_center_x - 1.2, arrow_tip_y - 1.5), 
                    fitz.Point(char_center_x, arrow_tip_y),
                    color=(0.8, 0.1, 0.1), 
                    width=1
                )
                page.draw_line(
                    fitz.Point(char_center_x + 1.2, arrow_tip_y - 1.5), 
                    fitz.Point(char_center_x, arrow_tip_y),
                    color=(0.8, 0.1, 0.1), 
                    width=1
                )

    doc.save(output_buffer, garbage=3, deflate=True)
    doc.close()


# =========================================================================
# STREAMLIT USER INTERFACE ENTRYPOINT
# =========================================================================
def main():
    st.set_page_config(page_title="Hebrew Tikun Annotator")
    
    # Initialize session state for adjustments
    if 'adj_score_x' not in st.session_state:
        st.session_state.adj_score_x = 0
    if 'adj_arrow_y' not in st.session_state:
        st.session_state.adj_arrow_y = 0
    if 'input_score_x' not in st.session_state:
        st.session_state.input_score_x = 0
    if 'input_arrow_y' not in st.session_state:
        st.session_state.input_arrow_y = 0

    st.title("📜 Hebrew Tikun PDF Annotator")
    
   # =====================================================================
    # ADJUSTMENT PANEL (SIDEBAR) - CORRECTED
    # =====================================================================
    with st.sidebar:
        st.header("⚙️ Adjustments")
        st.write("---")
        
        # Initialize session state keys for widgets if not present
        if 'slide_score' not in st.session_state:
            st.session_state.slide_score = 0
        if 'slide_arrow' not in st.session_state:
            st.session_state.slide_arrow = 0

        st.subheader("Line Annotations (X-axis)")
        st.slider("Shift position", -50, 50, key="slide_score")
        
        st.write("---")
        
        st.subheader("Red Arrows (Y-axis)")
        st.slider("Shift position", -20, 20, key="slide_arrow")
        
        st.write("---")
        col1, col2 = st.columns(2)
        
        if col1.button("Reset"):
            # Update processing variables
            st.session_state.adj_score_x = 0
            st.session_state.adj_arrow_y = 0
            # Update slider widget values directly via their keys
            st.session_state.slide_score = 0
            st.session_state.slide_arrow = 0
            st.rerun()
            
        if col2.button("Apply"):
            # Update processing variables from slider values
            st.session_state.adj_score_x = st.session_state.slide_score
            st.session_state.adj_arrow_y = st.session_state.slide_arrow
            st.rerun()

    st.write(
        "Upload a Hebrew Tikun PDF. Use the sidebar to adjust layout spacing "
        "and click **Apply** to re-process."
    )

    uploaded_file = st.file_uploader("Choose a Tikun PDF file to process", type=["pdf"])

    if uploaded_file is not None:
        output_pdf_buffer = io.BytesIO()
        
        with st.spinner("Analyzing text layout and inserting custom Hebrew annotations..."):
            try:
                generate_annotated_tikun_streamlit(
                    uploaded_file, 
                    output_pdf_buffer, 
                    st.session_state.adj_score_x, 
                    st.session_state.adj_arrow_y
                )
                st.success("Successfully processed and annotated PDF layout!")
                
                st.download_button(
                    label="📥 Download Annotated PDF",
                    data=output_pdf_buffer.getvalue(),
                    file_name="annotated_tikun_margins.pdf",
                    mime="application/pdf"
                )
            except Exception as e:
                st.error(f"Processing failed: {e}")

if __name__ == "__main__":
    main()
