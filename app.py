# app.py (Modified for Individual DOCX Output, Zip Download, Defaults, Timer, Title)

import streamlit as st
import backend  # Assumes backend.py is in the same directory
import os
import io # Changed from io import BytesIO to import io
import zipfile # NEW: For creating zip files
import logging
import time # NEW: Potentially for timing, mainly for calculating estimates

# Configure basic logging if needed
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Streamlit Page Configuration ---
st.set_page_config(
    page_title="Urdu extraction", # CHANGED: Page Title
    page_icon="📄",
    layout="wide"
)

# --- Initialize Session State ---
default_state = {
    # 'merged_doc_buffer': None, # REMOVED: No longer merging to single buffer
    'individual_results': [], # NEW: List to store {'filename': 'name.docx', 'buffer': BytesIO_obj}
    'zip_buffer': None, # NEW: Buffer for the downloadable zip file
    'files_processed_count': 0,
    'processing_complete': False,
    'processing_started': False,
    'ordered_files': [],  # List to hold UploadedFile objects in custom order
}
for key, value in default_state.items():
    if key not in st.session_state:
        st.session_state[key] = value

# --- Helper Functions ---
def reset_processing_state():
    """Resets state related to processing results and status."""
    # st.session_state.merged_doc_buffer = None # REMOVED
    st.session_state.individual_results = [] # NEW
    st.session_state.zip_buffer = None # NEW
    st.session_state.files_processed_count = 0
    st.session_state.processing_complete = False
    st.session_state.processing_started = False

# move_file (Unchanged)
def move_file(index, direction):
    """Moves the file at the given index up (direction=-1) or down (direction=1)."""
    files = st.session_state.ordered_files
    if not (0 <= index < len(files)): return
    new_index = index + direction
    if not (0 <= new_index < len(files)): return
    files[index], files[new_index] = files[new_index], files[index]
    st.session_state.ordered_files = files
    reset_processing_state() # Reset results if order changes

# remove_file (Unchanged)
def remove_file(index):
    """Removes the file at the given index."""
    files = st.session_state.ordered_files
    if 0 <= index < len(files):
        removed_file = files.pop(index)
        st.toast(f"Removed '{removed_file.name}'.")
        st.session_state.ordered_files = files
        reset_processing_state() # Reset results if list changes
    else:
        st.warning(f"Could not remove file at index {index} (already removed or invalid?).")

# handle_uploads (Unchanged)
def handle_uploads():
    """Adds newly uploaded files to the ordered list, avoiding duplicates by name."""
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
            reset_processing_state() # Reset results if list changes
            # Clear the uploader widget state after processing its contents
            # st.session_state.pdf_uploader = [] # Optional: Uncomment if you want uploader to clear visually

# clear_all_files_callback (Unchanged)
def clear_all_files_callback():
    """Clears the ordered file list and resets processing state."""
    st.session_state.ordered_files = []
    if 'pdf_uploader' in st.session_state:
        st.session_state.pdf_uploader = []
    reset_processing_state()
    st.toast("Removed all files from the list.")

# --- NEW: Helper Function to Create Zip Buffer ---
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
                # Ensure buffer position is at the beginning before reading
                buffer.seek(0)
                zipf.writestr(filename, buffer.getvalue())
            else:
                logging.warning(f"Skipping item in zip creation due to missing filename or buffer: {item.get('original_pdf_name', 'Unknown')}")
    zip_buffer.seek(0)
    return zip_buffer

# --- Page Title ---
st.title("📄 Urdu extraction - PDF to Word Converter") # CHANGED: Title
st.markdown("Upload PDF files (Urdu or Arabic script recommended), arrange their processing order, then process and download them as individual Word files.") # CHANGED: Description

# --- Sidebar ---
st.sidebar.header("⚙️ Configuration")

# API Key Input (Unchanged)
api_key_from_secrets = st.secrets.get("GEMINI_API_KEY", "")
api_key = st.sidebar.text_input(
    "Enter your Google Gemini API Key", type="password",
    help="Required. Get your key from Google AI Studio.", value=api_key_from_secrets or ""
)
# API Key Status Messages (Unchanged)
if api_key_from_secrets and api_key == api_key_from_secrets: st.sidebar.success("API Key loaded from Secrets.", icon="✅")
elif not api_key_from_secrets and not api_key: st.sidebar.warning("API Key not found or entered.", icon="🔑")
elif api_key and not api_key_from_secrets: st.sidebar.info("Using manually entered API Key.", icon="⌨️")
elif api_key and api_key_from_secrets and api_key != api_key_from_secrets: st.sidebar.info("Using manually entered API Key (overrides secret).", icon="⌨️")


st.sidebar.markdown("---") # Separator
st.sidebar.header("🧠 AI Model")
# Map user-friendly names to model IDs
model_options = {
    "Gemini 1.5 Flash (Fastest, Cost-Effective)": "gemini-1.5-flash-latest",
    "Gemini 1.5 Pro (Advanced, Slower, Higher Cost)": "gemini-1.5-pro-latest",
}
# Find the index for Pro model to set as default
pro_model_key = "Gemini 1.5 Pro (Advanced, Slower, Higher Cost)"
pro_model_index = list(model_options.keys()).index(pro_model_key) if pro_model_key in model_options else 0

selected_model_display_name = st.sidebar.selectbox(
    "Choose the Gemini model for processing:",
    options=list(model_options.keys()), # Use display names as options
    index=pro_model_index, # CHANGED: Default to Pro
    key="gemini_model_select",
    help="Select the AI model. Pro is more capable but slower and costs more."
)
# Get the actual model ID based on the user's selection
selected_model_id = model_options[selected_model_display_name]
st.sidebar.caption(f"Selected model ID: `{selected_model_id}`")

# Extraction Rules
st.sidebar.markdown("---") # Separator
st.sidebar.header("📜 Extraction Rules")
# CHANGED: Default Rules Text
default_rules = """Remove footnotes.
Identify and Completely Remove the header: Find the entire original top line of the page. This usually includes a page number and a title/heading (like كتاب الزكاة ), also content that may exist above the top line. All of this must be removed.
Do not remove headings inside main body text.
Structure the text into logical paragraphs based on the original document. Don't translate anything."""
rules_prompt = st.sidebar.text_area(
    "Enter the rules Gemini should follow:", value=default_rules, height=250,
    help="Provide clear instructions for how Gemini should process the extracted text."
)


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
        "✨ Process Files (Top)", # CHANGED: Label
        key="process_button_top", # Unique key
        use_container_width=True, type="primary",
        disabled=st.session_state.processing_started or not st.session_state.ordered_files
    )

with col_b2_top:
    # Show download button if zip buffer exists and not processing
    # if st.session_state.merged_doc_buffer and not st.session_state.processing_started: # REMOVED
    if st.session_state.zip_buffer and not st.session_state.processing_started: # NEW
        st.download_button(
            # CHANGED: Label, data, file_name, mime
            label=f"📥 Download All ({st.session_state.files_processed_count}) Files (.zip)",
            data=st.session_state.zip_buffer,
            file_name="extracted_urdu_documents.zip",
            mime="application/zip",
            key="download_zip_button_top", # Unique key
            use_container_width=True
        )
    elif st.session_state.processing_started:
        st.info("Processing in progress...", icon="⏳")
    else:
        # Placeholder or message when download isn't ready
        st.markdown("*(Download button for ZIP archive appears here after processing)*") # CHANGED


# Placeholders for top progress indicators
progress_bar_placeholder_top = st.empty()
status_text_placeholder_top = st.empty()

st.markdown("---") # Separator before file list

# --- Interactive File List (Unchanged) ---
st.subheader(f"Files in Processing Order ({len(st.session_state.ordered_files)}):")

if not st.session_state.ordered_files:
    st.info("Use the uploader above to add files. They will appear here for ordering.")
else:
    # Header row (Unchanged)
    col_h1, col_h2, col_h3, col_h4, col_h5 = st.columns([0.5, 5, 1, 1, 1])
    with col_h1: st.markdown("**#**")
    with col_h2: st.markdown("**Filename**")
    with col_h3: st.markdown("**Up**")
    with col_h4: st.markdown("**Down**")
    with col_h5: st.markdown("**Remove**")

    # File rows (Unchanged)
    for i, file in enumerate(st.session_state.ordered_files):
        col1, col2, col3, col4, col5 = st.columns([0.5, 5, 1, 1, 1])
        with col1: st.write(f"{i+1}")
        with col2: st.write(file.name)
        with col3: st.button("⬆️", key=f"up_{i}", on_click=move_file, args=(i, -1), disabled=(i == 0), help="Move Up")
        with col4: st.button("⬇️", key=f"down_{i}", on_click=move_file, args=(i, 1), disabled=(i == len(st.session_state.ordered_files) - 1), help="Move Down")
        with col5: st.button("❌", key=f"del_{i}", on_click=remove_file, args=(i,), help="Remove")

    # Clear all button (Unchanged)
    st.button("🗑️ Remove All Files",
              key="remove_all_button",
              on_click=clear_all_files_callback,
              help="Click to remove all files from the list.",
              type="secondary")


st.markdown("---") # Separator after file list

# --- BOTTOM: Buttons Area & Progress Indicators ---
st.subheader("🚀 Actions & Progress (Bottom)")
col_b1_bottom, col_b2_bottom = st.columns([3, 2])

with col_b1_bottom:
    process_button_bottom_clicked = st.button(
        "✨ Process Files (Bottom)", # CHANGED: Label
        key="process_button_bottom", # Unique key
        use_container_width=True, type="primary",
        disabled=st.session_state.processing_started or not st.session_state.ordered_files
    )

with col_b2_bottom:
    # Show download button if zip buffer exists and not processing
    # if st.session_state.merged_doc_buffer and not st.session_state.processing_started: # REMOVED
    if st.session_state.zip_buffer and not st.session_state.processing_started: # NEW
        st.download_button(
             # CHANGED: Label, data, file_name, mime
            label=f"📥 Download All ({st.session_state.files_processed_count}) Files (.zip)",
            data=st.session_state.zip_buffer,
            file_name="extracted_urdu_documents.zip",
            mime="application/zip",
            key="download_zip_button_bottom", # Unique key
            use_container_width=True
        )
    elif st.session_state.processing_started:
        st.info("Processing in progress...", icon="⏳")
    else:
        # Placeholder or message when download isn't ready
        st.markdown("*(Download button for ZIP archive appears here after processing)*") # CHANGED

# Placeholders for bottom progress indicators
progress_bar_placeholder_bottom = st.empty()
status_text_placeholder_bottom = st.empty()

# --- Container for Individual File Results (Displayed below bottom progress) ---
results_container = st.container()


# --- Processing Logic ---
# Check if EITHER process button was clicked
if process_button_top_clicked or process_button_bottom_clicked:
    reset_processing_state()
    st.session_state.processing_started = True

    # Re-check conditions (Unchanged checks, maybe add rules prompt check)
    if not st.session_state.ordered_files:
        st.warning("⚠️ No files in the list to process.")
        st.session_state.processing_started = False
    elif not api_key:
        st.error("❌ Please enter or configure your Gemini API Key in the sidebar.")
        st.session_state.processing_started = False
    elif not rules_prompt:
         # Make rule prompt emptiness a warning, not blocking
        st.warning("⚠️ The 'Extraction Rules' field is empty. Processing with default model behavior might be less predictable.")
    elif not selected_model_id:
        st.error("❌ No Gemini model selected in the sidebar.") # Should not happen with default
        st.session_state.processing_started = False

    # Proceed only if checks passed (API Key and files exist)
    if st.session_state.ordered_files and api_key and st.session_state.processing_started and selected_model_id:

        # MODIFIED: Store individual results here
        # processed_doc_streams = [] # REMOVED
        individual_results_temp = [] # Use a temporary list during processing

        total_files = len(st.session_state.ordered_files)
        TIME_PER_PDF_ESTIMATE_S = 200 # NEW: Estimate in seconds

        # Initialize BOTH progress bars
        progress_bar_top = progress_bar_placeholder_top.progress(0, text="Starting processing...")
        progress_bar_bottom = progress_bar_placeholder_bottom.progress(0, text="Starting processing...")

        # Clear previous results visually
        results_container.empty()

        for i, file_to_process in enumerate(st.session_state.ordered_files):
            original_filename = file_to_process.name
            base_filename, _ = os.path.splitext(original_filename)
            target_word_filename = f"{base_filename}.docx" # NEW: Target .docx filename

            current_file_status = f"'{original_filename}' ({i + 1}/{total_files})"

            # --- NEW: Calculate Estimated Remaining Time ---
            remaining_files = total_files - i
            remaining_time_estimate_s = remaining_files * TIME_PER_PDF_ESTIMATE_S
            remaining_minutes = int(remaining_time_estimate_s // 60)
            remaining_seconds_part = int(remaining_time_estimate_s % 60)
            time_estimate_str = f"Est. time remaining: {remaining_minutes}m {remaining_seconds_part}s"
            # ---

            progress_text = f"Processing {current_file_status}. {time_estimate_str}" # CHANGED: Add time estimate

            # Update BOTH progress bars and status texts
            progress_value = i / total_files
            progress_bar_top.progress(progress_value, text=progress_text)
            progress_bar_bottom.progress(progress_value, text=progress_text)
            status_text_placeholder_top.info(f"🔄 Starting {current_file_status}")
            status_text_placeholder_bottom.info(f"🔄 Starting {current_file_status}")

            with results_container:
                st.markdown(f"--- \n**Processing: {original_filename}**")

            raw_text = None
            processed_text = ""
            extraction_error = False
            gemini_error_occurred = False
            word_creation_error_occurred = False
            word_doc_stream = None # Initialize stream for this file

            # 1. Extract Text
            status_text_placeholder_top.info(f"📄 Extracting text from {current_file_status}...")
            status_text_placeholder_bottom.info(f"📄 Extracting text from {current_file_status}...")
            try:
                file_to_process.seek(0) # Ensure reading from start
                raw_text = backend.extract_text_from_pdf(file_to_process)
                if raw_text is None: # Should ideally not happen if backend returns "" or "Error:"
                    with results_container: st.error(f"❌ Critical error during text extraction (None returned). Skipping '{original_filename}'.")
                    extraction_error = True
                elif isinstance(raw_text, str) and raw_text.startswith("Error:"):
                    with results_container: st.error(f"❌ Error extracting text from '{original_filename}': {raw_text}")
                    extraction_error = True
                elif not raw_text or not raw_text.strip():
                    with results_container: st.warning(f"⚠️ No text extracted from '{original_filename}'. A placeholder Word file will be created.")
                    processed_text = "" # Ensure processed text is empty for placeholder creation later
                # else: Text extracted successfully

            except Exception as ext_exc:
                with results_container: st.error(f"❌ Unexpected error during text extraction for '{original_filename}': {ext_exc}")
                extraction_error = True

            # 2. Process with Gemini
            if not extraction_error and raw_text and raw_text.strip():
                status_text_placeholder_top.info(f"🤖 Sending text from {current_file_status} to Gemini ({selected_model_display_name})...")
                status_text_placeholder_bottom.info(f"🤖 Sending text from {current_file_status} to Gemini ({selected_model_display_name})...")
                try:
                    # Pass selected_model_id to backend (Unchanged call)
                    processed_text_result = backend.process_text_with_gemini(
                        api_key, raw_text, rules_prompt, selected_model_id
                    )

                    if processed_text_result is None or (isinstance(processed_text_result, str) and processed_text_result.startswith("Error:")):
                        error_msg = processed_text_result or 'Unknown API error / empty response'
                        with results_container: st.error(f"❌ Gemini error for '{original_filename}': {error_msg}")
                        gemini_error_occurred = True
                        processed_text = "" # Use empty string for Word doc
                    else:
                        processed_text = processed_text_result
                except Exception as gem_exc:
                    with results_container: st.error(f"❌ Unexpected error during Gemini processing for '{original_filename}': {gem_exc}")
                    gemini_error_occurred = True
                    processed_text = "" # Use empty string for Word doc
            elif not extraction_error and (not raw_text or not raw_text.strip()):
                # Case where extraction yielded no text, skip Gemini
                processed_text = ""


            # 3. Create Individual Word Document
            # This step now happens even if extraction/Gemini failed, to create placeholder docs
            if not extraction_error: # Only skip if extraction itself had a critical failure
                status_text_placeholder_top.info(f"📝 Creating Word document '{target_word_filename}'...")
                status_text_placeholder_bottom.info(f"📝 Creating Word document '{target_word_filename}'...")
                try:
                    # Pass the processed_text (could be empty or from Gemini)
                    word_doc_stream = backend.create_word_document(processed_text)

                    if word_doc_stream:
                        # --- Store individual result ---
                        individual_results_temp.append({
                            'original_pdf_name': original_filename,
                            'filename': target_word_filename,
                            'buffer': word_doc_stream
                         })
                        # ---

                        with results_container:
                            success_msg = f"✅ Created Word file: '{target_word_filename}'."
                            if gemini_error_occurred:
                                success_msg += " (Note: Used placeholder text due to Gemini error)"
                            elif not processed_text and raw_text and raw_text.strip(): # Had raw text, but Gemini result was empty/error
                                 success_msg += " (Note: Gemini result was empty or blocked, used placeholder text)"
                            elif not processed_text and (not raw_text or not raw_text.strip()): # No text extracted initially
                                success_msg += " (Note: Based on empty extracted text)"
                            st.success(success_msg)
                    else:
                        word_creation_error_occurred = True
                        with results_container: st.error(f"❌ Failed to create Word file '{target_word_filename}' (backend returned None).")
                except Exception as doc_exc:
                    word_creation_error_occurred = True
                    with results_container: st.error(f"❌ Error creating Word file '{target_word_filename}': {doc_exc}")
            else:
                 with results_container: st.warning(f"ℹ️ Skipped Word file creation for '{original_filename}' due to text extraction failure.")


            # Update overall progress on BOTH bars (Unchanged logic, text updated earlier)
            status_msg_suffix = ""
            if extraction_error or word_creation_error_occurred or gemini_error_occurred: status_msg_suffix = " with issues."
            final_progress_value = (i + 1) / total_files
            # Re-calculate remaining time for final text to be accurate if loop is fast
            final_remaining_files = total_files - (i + 1)
            final_remaining_time_s = final_remaining_files * TIME_PER_PDF_ESTIMATE_S
            final_rem_min = int(final_remaining_time_s // 60)
            final_rem_sec = int(final_remaining_time_s % 60)
            final_time_str = f"Est. time remaining: {final_rem_min}m {final_rem_sec}s" if final_remaining_files > 0 else "Finishing..."

            final_progress_text = f"Processed {current_file_status}{status_msg_suffix}. {final_time_str}"
            progress_bar_top.progress(final_progress_value, text=final_progress_text)
            progress_bar_bottom.progress(final_progress_value, text=final_progress_text)

        # --- End of file loop ---

        # Clear BOTH progress bars and status texts
        progress_bar_placeholder_top.empty()
        status_text_placeholder_top.empty()
        progress_bar_placeholder_bottom.empty()
        status_text_placeholder_bottom.empty()

        # --- NEW: Create Zip file from results ---
        final_status_message = ""
        rerun_needed = False
        successfully_created_doc_count = len(individual_results_temp)

        with results_container:
            st.markdown("---") # Separator before final status
            if successfully_created_doc_count > 0:
                st.info(f"💾 Creating ZIP archive containing {successfully_created_doc_count} Word document(s)...")
                try:
                    zip_buffer = create_zip_buffer(individual_results_temp)
                    if zip_buffer:
                        st.session_state.zip_buffer = zip_buffer # Store for download button
                        st.session_state.individual_results = individual_results_temp # Store results list too
                        st.session_state.files_processed_count = successfully_created_doc_count
                        final_status_message = f"✅ Processing complete! Created {successfully_created_doc_count} Word file(s). Click 'Download All' above or below to get the ZIP archive."
                        st.success(final_status_message)
                        rerun_needed = True # Rerun to show download buttons
                    else:
                        final_status_message = "❌ Failed to create ZIP archive (zip function returned None)."
                        st.error(final_status_message)
                except Exception as zip_exc:
                    final_status_message = f"❌ Error during ZIP archive creation: {zip_exc}"
                    logging.error(f"Error during create_zip_buffer call: {zip_exc}", exc_info=True)
                    st.error(final_status_message)
            else:
                final_status_message = "⚠️ No Word documents were successfully created to include in a ZIP archive."
                st.warning(final_status_message)
                if st.session_state.ordered_files: st.info("Please check the individual file statuses above for errors.")


        st.session_state.processing_complete = True
        st.session_state.processing_started = False

        if rerun_needed:
            st.rerun() # Rerun to make download buttons visible / update UI state

    else:
        # Processing didn't start due to initial checks failing
        if not st.session_state.ordered_files or not api_key or not selected_model_id:
             st.session_state.processing_started = False # Ensure it's reset if checks failed


# --- Fallback info message (Unchanged) ---
if not st.session_state.ordered_files and not st.session_state.processing_started and not st.session_state.processing_complete:
    st.info("Upload PDF files using the 'Choose PDF files' button above.")

# --- Footer (Unchanged) ---
st.markdown("---")
st.markdown("Developed with Streamlit, Google Gemini, and Google Cloud Vision.") # Slightly updated footer
