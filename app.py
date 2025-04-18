# app.py (Modified with updated default rules and previous zip filename change)

import streamlit as st
import backend  # Assumes backend.py is in the same directory
import os
import io
import zipfile # For creating zip files
import logging
import time # For calculating estimates

# Configure basic logging if needed
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Streamlit Page Configuration ---
st.set_page_config(
    page_title="Urdu extraction",
    page_icon="📘", # Changed icon
    layout="wide"
)

# --- Initialize Session State ---
default_state = {
    'split_results': [],
    'zip_buffer': None,
    'files_processed_count': 0,
    'split_files_count': 0,
    'processing_complete': False,
    'processing_started': False,
    'ordered_files': [],
    'zip_filename': "split_urdu_documents.zip", # Default zip filename
}
for key, value in default_state.items():
    if key not in st.session_state:
        st.session_state[key] = value

# --- Helper Functions ---
def reset_processing_state():
    """Resets state related to processing results and status."""
    st.session_state.split_results = []
    st.session_state.zip_buffer = None
    st.session_state.files_processed_count = 0
    st.session_state.split_files_count = 0
    st.session_state.processing_complete = False
    st.session_state.processing_started = False
    st.session_state.zip_filename = "split_urdu_documents.zip" # Reset zip filename to default

# move_file (Unchanged)
def move_file(index, direction):
    files = st.session_state.ordered_files
    if not (0 <= index < len(files)): return
    new_index = index + direction
    if not (0 <= new_index < len(files)): return
    files[index], files[new_index] = files[new_index], files[index]
    st.session_state.ordered_files = files
    reset_processing_state() # Reset results if order changes

# remove_file (Unchanged)
def remove_file(index):
    files = st.session_state.ordered_files
    if 0 <= index < len(files):
        removed_file = files.pop(index)
        st.toast(f"Removed '{removed_file.name}'.")
        st.session_state.ordered_files = files
        reset_processing_state() # Reset results if file removed
    else:
        st.warning(f"Could not remove file at index {index} (already removed or invalid?).")

# handle_uploads (Unchanged)
def handle_uploads():
    if 'pdf_uploader' in st.session_state and st.session_state.pdf_uploader:
        current_filenames = {f.name for f in st.session_state.ordered_files}
        new_files_added_count = 0
        for uploaded_file in st.session_state.pdf_uploader:
            if uploaded_file.name not in current_filenames:
                st.session_state.ordered_files.append(uploaded_file)
                current_filenames.add(uploaded_file.name)
                new_files_added_count += 1
        if new_files_added_count > 0:
            st.toast(f"Added {new_files_added_count} new file(s) to the end of the list.")
            reset_processing_state() # Reset results if new files added

# clear_all_files_callback (Unchanged)
def clear_all_files_callback():
    st.session_state.ordered_files = []
    if 'pdf_uploader' in st.session_state:
        st.session_state.pdf_uploader = []
    reset_processing_state()
    st.toast("Removed all files from the list.")

# --- Create Zip Buffer Helper (Unchanged) ---
def create_zip_buffer(results_list):
    """Creates a zip file in memory containing multiple docx files."""
    if not results_list:
        return None
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for item in results_list:
            filename = item.get('filename')
            buffer = item.get('buffer')
            if filename and buffer and hasattr(buffer, 'getvalue'):
                buffer.seek(0)
                zipf.writestr(filename, buffer.getvalue())
            else:
                logging.warning(f"Skipping item in zip creation due to missing filename or buffer.")
    zip_buffer.seek(0)
    return zip_buffer

# --- Page Title & Description (Unchanged) ---
st.title("📘 Urdu extraction - PDF to Word Converter")
st.markdown("Upload PDF files (Urdu or Arabic script recommended), arrange order, process, merge, split into ~8-page parts, and download as a ZIP archive.")

# --- Sidebar ---
st.sidebar.header("⚙️ Configuration")
# API Key Input
api_key_from_secrets = st.secrets.get("GEMINI_API_KEY", "")
api_key = st.sidebar.text_input(
    "Enter your Google Gemini API Key", type="password",
    help="Required. Get your key from Google AI Studio.", value=api_key_from_secrets or ""
)
# API Key Status Messages
if api_key_from_secrets and api_key == api_key_from_secrets: st.sidebar.success("API Key loaded from Secrets.", icon="✅")
elif not api_key_from_secrets and not api_key: st.sidebar.warning("API Key not found or entered.", icon="🔑")
elif api_key and not api_key_from_secrets: st.sidebar.info("Using manually entered API Key.", icon="⌨️")
elif api_key and api_key_from_secrets and api_key != api_key_from_secrets: st.sidebar.info("Using manually entered API Key (overrides secret).", icon="⌨️")

# Model Selection
st.sidebar.markdown("---")
st.sidebar.header("🧠 AI Model")
model_options = {
    "Gemini 1.5 Flash (Fastest, Cost-Effective)": "gemini-1.5-flash-latest",
    "Gemini 1.5 Pro (Advanced, Slower, Higher Cost)": "gemini-1.5-pro-latest",
}
flash_model_key = "Gemini 1.5 Flash (Fastest, Cost-Effective)"
flash_model_index = list(model_options.keys()).index(flash_model_key) if flash_model_key in model_options else 0
selected_model_display_name = st.sidebar.selectbox(
    "Choose the Gemini model for processing:",
    options=list(model_options.keys()),
    index=flash_model_index,
    key="gemini_model_select",
    help="Select the AI model. Flash is faster and cheaper. Pro is more capable but slower and costs more."
)
selected_model_id = model_options[selected_model_display_name]
st.sidebar.caption(f"Selected model ID: `{selected_model_id}`")

# Extraction Rules
st.sidebar.markdown("---")
st.sidebar.header("📜 Extraction Rules")
# <<< CHANGE: Updated default rules based on user request >>>
default_rules = """Remove the header.
Identify and Completely Remove the header: Find the entire original top line of the page. This usually includes a page number and a title/heading (like كتاب الزكاة ), also content that may exist above the top line. All of this must be removed.
Do not remove headings inside main body text.
Structure the text into logical paragraphs based on the original document. Don't translate anything."""
rules_prompt = st.sidebar.text_area(
    "Enter the rules Gemini should follow:", value=default_rules, height=200,
    help="Provide clear instructions for how Gemini should process the extracted text."
)
# --- End Sidebar ---


# --- Main Area ---
st.header("📁 Manage Files for Processing")

# File Uploader (Unchanged)
uploaded_files_widget = st.file_uploader(
    "Choose PDF files to add to the list below:", type="pdf", accept_multiple_files=True,
    key="pdf_uploader",
    on_change=handle_uploads,
    label_visibility="visible"
)

st.markdown("---")

# --- TOP: Buttons Area & Progress Indicators ---
st.subheader("🚀 Actions & Progress (Top)")
col_b1_top, col_b2_top = st.columns([3, 2])

with col_b1_top:
    process_button_top_clicked = st.button(
        "✨ Process, Merge & Split Files (Top)",
        key="process_button_top",
        use_container_width=True, type="primary",
        disabled=st.session_state.processing_started or not st.session_state.ordered_files
    )

with col_b2_top:
    # Download button for the ZIP of SPLIT files
    # Uses dynamic zip filename from session state
    if st.session_state.zip_buffer and not st.session_state.processing_started and st.session_state.zip_filename:
        st.download_button(
            label=f"📥 Download All ({st.session_state.split_files_count}) Split Files (.zip)",
            data=st.session_state.zip_buffer,
            file_name=st.session_state.zip_filename, # Uses dynamic name
            mime="application/zip",
            key="download_zip_button_top",
            use_container_width=True
        )
    elif st.session_state.processing_started:
        st.info("Processing in progress...", icon="⏳")
    else:
        st.markdown("*(Download button for ZIP of split files appears here)*")

# Placeholders for top progress indicators
progress_bar_placeholder_top = st.empty()
status_text_placeholder_top = st.empty()

st.markdown("---") # Separator before file list

# --- Interactive File List (Unchanged) ---
st.subheader(f"Files in Processing Order ({len(st.session_state.ordered_files)}):")
if not st.session_state.ordered_files:
    st.info("Use the uploader above to add files. They will appear here for ordering.")
else:
    # Header/Rows
    col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns([0.5, 5, 1, 1, 1])
    with col_h1: st.markdown("**#**")
    with col_h2: st.markdown("**Filename**")
    with col_h3: st.markdown("**Up**")
    with col_h4: st.markdown("**Down**")
    with col_h5: st.markdown("**Remove**")

    # File rows loop
    for i, file in enumerate(st.session_state.ordered_files):
        col1, col2, col3, col4, col5 = st.columns([0.5, 5, 1, 1, 1])
        with col1: st.write(f"{i+1}")
        with col2: st.write(file.name)
        with col3: st.button("⬆️", key=f"up_{i}", on_click=move_file, args=(i, -1), disabled=(i == 0), help="Move Up")
        with col4: st.button("⬇️", key=f"down_{i}", on_click=move_file, args=(i, 1), disabled=(i == len(st.session_state.ordered_files) - 1), help="Move Down")
        with col5: st.button("❌", key=f"del_{i}", on_click=remove_file, args=(i,), help="Remove")

    # Clear all button
    st.button("🗑️ Remove All Files", key="remove_all_button", on_click=clear_all_files_callback, help="Click to remove all files from the list.", type="secondary")


st.markdown("---") # Separator after file list

# --- BOTTOM: Buttons Area & Progress Indicators ---
st.subheader("🚀 Actions & Progress (Bottom)")
col_b1_bottom, col_b2_bottom = st.columns([3, 2])

with col_b1_bottom:
    process_button_bottom_clicked = st.button(
        "✨ Process, Merge & Split Files (Bottom)",
        key="process_button_bottom",
        use_container_width=True, type="primary",
        disabled=st.session_state.processing_started or not st.session_state.ordered_files
    )

with col_b2_bottom:
    # Download button for the ZIP of SPLIT files
    # Uses dynamic zip filename from session state
    if st.session_state.zip_buffer and not st.session_state.processing_started and st.session_state.zip_filename:
        st.download_button(
            label=f"📥 Download All ({st.session_state.split_files_count}) Split Files (.zip)",
            data=st.session_state.zip_buffer,
            file_name=st.session_state.zip_filename, # Uses dynamic name
            mime="application/zip",
            key="download_zip_button_bottom",
            use_container_width=True
        )
    elif st.session_state.processing_started:
        st.info("Processing in progress...", icon="⏳")
    else:
        st.markdown("*(Download button for ZIP of split files appears here)*")

# Placeholders for bottom progress indicators
progress_bar_placeholder_bottom = st.empty()
status_text_placeholder_bottom = st.empty()

# --- Container for Individual File Results (Displayed below bottom progress) ---
results_container = st.container()


# --- Processing Logic ---
if process_button_top_clicked or process_button_bottom_clicked:
    reset_processing_state() # Reset includes zip_filename to default initially
    st.session_state.processing_started = True

    # Re-check conditions (Unchanged checks)
    if not st.session_state.ordered_files:
        st.warning("⚠️ No files in the list to process.")
        st.session_state.processing_started = False
    elif not api_key:
        st.error("❌ Please enter or configure your Gemini API Key in the sidebar.")
        st.session_state.processing_started = False
    elif not rules_prompt:
        # Use the default rules if the text area is somehow empty
        # (though it's initialized with the default)
        st.warning("⚠️ The 'Extraction Rules' field was empty. Using default rules.")
        active_rules_prompt = default_rules # Use the default defined above
    elif not selected_model_id:
        st.error("❌ No Gemini model selected in the sidebar.")
        st.session_state.processing_started = False
    else:
        active_rules_prompt = rules_prompt # Use rules from text area

    # Proceed only if checks passed
    if st.session_state.ordered_files and api_key and st.session_state.processing_started and selected_model_id:

        # Determine dynamic zip filename from first file
        try:
            first_file_name = st.session_state.ordered_files[0].name
            base_name = os.path.splitext(first_file_name)[0]
            st.session_state.zip_filename = f"{base_name}.zip"
            logging.info(f"Set output ZIP filename to: {st.session_state.zip_filename}")
        except Exception as e:
            logging.error(f"Could not determine filename from first file: {e}. Using default.")
            # Keep the default name set in reset_processing_state()

        # Store intermediate doc streams for merging
        intermediate_doc_streams = [] # List of tuples: (original_filename, BytesIO_buffer)

        total_files = len(st.session_state.ordered_files)
        TIME_PER_PDF_ESTIMATE_S = 15 # Estimate in seconds
        total_steps = total_files + 2 # Add 2 steps for merge and split
        current_step = 0

        progress_bar_top = progress_bar_placeholder_top.progress(0, text="Starting processing...")
        progress_bar_bottom = progress_bar_placeholder_bottom.progress(0, text="Starting processing...")
        results_container.empty() # Clear previous results visually

        # --- Stage 1: Process each file individually ---
        files_processed_ok_count = 0
        for i, file_to_process in enumerate(st.session_state.ordered_files):
            current_step = i + 1
            progress_value = current_step / total_steps
            original_filename = file_to_process.name
            current_file_status = f"'{original_filename}' ({i + 1}/{total_files})"

            # Calculate Estimated Remaining Time
            remaining_files_in_stage = total_files - i
            remaining_time_estimate_s = remaining_files_in_stage * TIME_PER_PDF_ESTIMATE_S + 10 # +10s for merge/split approx
            remaining_minutes = int(remaining_time_estimate_s // 60)
            remaining_seconds_part = int(remaining_time_estimate_s % 60)
            time_estimate_str = f"Est. time remaining: {remaining_minutes}m {remaining_seconds_part}s"
            progress_text = f"Processing {current_file_status}. {time_estimate_str}"

            # Update progress bars and status texts
            progress_bar_top.progress(progress_value, text=progress_text)
            progress_bar_bottom.progress(progress_value, text=progress_text)
            status_text_placeholder_top.info(f"🔄 Starting {current_file_status}")
            status_text_placeholder_bottom.info(f"🔄 Starting {current_file_status}")

            with results_container:
                st.markdown(f"--- \n**Processing: {original_filename}**")

            raw_text = None; processed_text = ""; word_doc_stream = None
            extraction_error = False; gemini_error_occurred = False; word_creation_error_occurred = False

            # 1. Extract Text
            status_text_placeholder_top.info(f"📄 Extracting text from {current_file_status}...")
            status_text_placeholder_bottom.info(f"📄 Extracting text from {current_file_status}...")
            try:
                file_to_process.seek(0)
                raw_text = backend.extract_text_from_pdf(file_to_process)
                if raw_text is None: raise ValueError("Backend extraction returned None")
                if isinstance(raw_text, str) and raw_text.startswith("Error:"):
                    with results_container: st.error(f"❌ Error extracting text: {raw_text}")
                    extraction_error = True
                elif not raw_text or not raw_text.strip():
                    with results_container: st.warning(f"⚠️ No text extracted. Placeholder Word content will be used.")
                    processed_text = "" # Ensure processed_text is empty for placeholder logic
            except Exception as ext_exc:
                with results_container: st.error(f"❌ Text extraction failed: {ext_exc}")
                extraction_error = True

            # 2. Process with Gemini (if text extracted)
            if not extraction_error and raw_text and raw_text.strip():
                status_text_placeholder_top.info(f"🤖 Sending text to Gemini ({selected_model_display_name})...")
                status_text_placeholder_bottom.info(f"🤖 Sending text to Gemini ({selected_model_display_name})...")
                try:
                    # Use active_rules_prompt determined earlier
                    processed_text_result = backend.process_text_with_gemini(api_key, raw_text, active_rules_prompt, selected_model_id)
                    if processed_text_result is None: raise ValueError("Backend Gemini processing returned None")
                    if isinstance(processed_text_result, str) and processed_text_result.startswith("Error:"):
                        with results_container: st.error(f"❌ Gemini processing error: {processed_text_result}")
                        gemini_error_occurred = True; processed_text = "" # Fallback to empty
                    else:
                        processed_text = processed_text_result
                        if not processed_text.strip():
                            with results_container: st.warning(f"⚠️ Gemini returned empty text.")
                except Exception as gem_exc:
                    with results_container: st.error(f"❌ Gemini processing failed: {gem_exc}")
                    gemini_error_occurred = True; processed_text = "" # Fallback to empty

            # 3. Create Intermediate Word Document
            if not extraction_error:
                status_text_placeholder_top.info(f"📝 Creating intermediate Word doc for {current_file_status}...")
                status_text_placeholder_bottom.info(f"📝 Creating intermediate Word doc for {current_file_status}...")
                try:
                    word_doc_stream = backend.create_word_document(processed_text) # Handles empty text internally
                    if word_doc_stream:
                        intermediate_doc_streams.append((original_filename, word_doc_stream))
                        files_processed_ok_count += 1
                        with results_container:
                            success_msg = f"✅ Created intermediate Word file for merging."
                            if gemini_error_occurred: success_msg += " (Used placeholder due to Gemini error)"
                            elif not processed_text and raw_text and raw_text.strip(): success_msg += " (Used placeholder as Gemini result was empty)"
                            elif not processed_text and (not raw_text or not raw_text.strip()): success_msg += " (Based on empty extracted text)"
                            st.success(success_msg)
                    else:
                        word_creation_error_occurred = True
                        with results_container: st.error(f"❌ Failed to create intermediate Word file (backend returned None).")
                except Exception as doc_exc:
                    word_creation_error_occurred = True
                    with results_container: st.error(f"❌ Error creating intermediate Word file: {doc_exc}")
            else:
                 with results_container: st.warning(f"ℹ️ Skipped intermediate Word file creation due to text extraction failure.")

        # --- End of file processing loop ---
        st.session_state.files_processed_count = files_processed_ok_count

        # --- Stage 2: Merge Documents ---
        merged_doc_buffer = None
        if intermediate_doc_streams:
            current_step = total_files + 1
            progress_value = current_step / total_steps
            merge_status_text = f"Merging {len(intermediate_doc_streams)} intermediate document(s)..."
            progress_bar_top.progress(progress_value, text=merge_status_text)
            progress_bar_bottom.progress(progress_value, text=merge_status_text)
            status_text_placeholder_top.info(f"💾 {merge_status_text}")
            status_text_placeholder_bottom.info(f"💾 {merge_status_text}")
            with results_container: st.markdown("---"); st.info(f"💾 {merge_status_text}")

            try:
                merged_doc_buffer = backend.merge_word_documents(intermediate_doc_streams)
                if not merged_doc_buffer:
                    with results_container: st.error("❌ Document merging failed (backend returned None). Cannot proceed to splitting.")
                else:
                     with results_container: st.success("✅ Intermediate documents merged successfully.")
            except Exception as merge_exc:
                with results_container: st.error(f"❌ Document merging failed: {merge_exc}. Cannot proceed to splitting.")
                merged_doc_buffer = None
        else:
            with results_container: st.warning("⚠️ No intermediate documents were created successfully. Skipping merge and split.")

        # --- Stage 3: Split Merged Document ---
        split_results_final = []
        if merged_doc_buffer:
            current_step = total_files + 2
            progress_value = current_step / total_steps
            split_status_text = "Splitting merged document into parts (approx. 8 pages each)..."
            progress_bar_top.progress(progress_value, text=split_status_text)
            progress_bar_bottom.progress(progress_value, text=split_status_text)
            status_text_placeholder_top.info(f"✂️ {split_status_text}")
            status_text_placeholder_bottom.info(f"✂️ {split_status_text}")
            with results_container: st.markdown("---"); st.info(f"✂️ {split_status_text}")

            try:
                paragraphs_to_target_8_pages = 60 # Approx 60 paragraphs -> ~8 pages
                split_results_final = backend.split_word_document(merged_doc_buffer, paragraphs_per_split=paragraphs_to_target_8_pages)
                st.session_state.split_results = split_results_final
                st.session_state.split_files_count = len(split_results_final)

                if not split_results_final:
                     with results_container: st.warning("⚠️ Splitting resulted in zero output files.")
                else:
                     with results_container: st.success(f"✅ Merged document split into {st.session_state.split_files_count} part(s).")
            except Exception as split_exc:
                with results_container: st.error(f"❌ Document splitting failed: {split_exc}")
                split_results_final = []
        else:
             with results_container: st.info("ℹ️ Skipping splitting because merging failed or produced no output.")


        # --- Stage 4: Create Zip Archive ---
        final_status_message = ""
        rerun_needed = False
        if split_results_final:
            status_text_placeholder_top.info("📦 Creating final ZIP archive...")
            status_text_placeholder_bottom.info("📦 Creating final ZIP archive...")
            with results_container: st.info("📦 Creating final ZIP archive...")
            try:
                zip_buffer_final = create_zip_buffer(split_results_final)
                if zip_buffer_final:
                    st.session_state.zip_buffer = zip_buffer_final # Store for download
                    # Updated message to mention the dynamic zip filename
                    final_status_message = f"✅ Processing complete! Generated {st.session_state.split_files_count} split Word file(s). Click 'Download All' (using name '{st.session_state.zip_filename}') above or below."
                    with results_container: st.success(final_status_message)
                    rerun_needed = True # Rerun to show download buttons
                else:
                    final_status_message = "❌ Failed to create final ZIP archive."
                    with results_container: st.error(final_status_message)
            except Exception as zip_exc:
                final_status_message = f"❌ Error during ZIP archive creation: {zip_exc}"
                with results_container: st.error(final_status_message)
        else:
            # Determine final message if splitting didn't happen or failed
            if not intermediate_doc_streams:
                 final_status_message = "⚠️ Processing finished, but no documents were successfully processed or merged."
            elif not merged_doc_buffer:
                 final_status_message = "⚠️ Processing finished, but merging failed. No split files generated."
            else: # Merging likely worked, but splitting failed or produced nothing
                 final_status_message = "⚠️ Processing finished, merging succeeded, but splitting failed or produced no files."
            with results_container: st.warning(final_status_message)


        # --- Final Cleanup ---
        progress_bar_placeholder_top.empty()
        status_text_placeholder_top.empty()
        progress_bar_placeholder_bottom.empty()
        status_text_placeholder_bottom.empty()

        st.session_state.processing_complete = True
        st.session_state.processing_started = False

        if rerun_needed:
            st.rerun() # Rerun to make download buttons visible

    else:
        # Processing didn't start due to initial checks failing
        st.session_state.processing_started = False # Ensure reset


# --- Fallback info message (Unchanged) ---
if not st.session_state.ordered_files and not st.session_state.processing_started and not st.session_state.processing_complete:
    st.info("Upload PDF files using the 'Choose PDF files' button above.")

# --- Footer (Unchanged) ---
st.markdown("---")
st.markdown("Developed with Streamlit, Google Gemini, and Google Cloud Vision.")
