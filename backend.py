# backend.py (with Merging Restored and New Splitting Function)

import io
import google.generativeai as genai
from docx import Document
from docx.shared import Pt # Import Pt for font size if needed
from docx.enum.text import WD_ALIGN_PARAGRAPH # Required for alignment constant
from docx.oxml.ns import qn # For setting complex script font correctly
from docx.oxml import OxmlElement # Needed for creating font elements if missing
import logging
import os
import streamlit as st
import json
from google.cloud import vision
from docxcompose.composer import Composer # Keep for merging
import copy # Needed for deep copying elements during split

# --- Configure Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')

# --- START: Runtime Credentials Setup for Streamlit Cloud (Unchanged) ---
# (Keep the existing credentials setup block exactly as it was)
# Define the path for the temporary credentials file within the container's filesystem
CREDENTIALS_FILENAME = "google_credentials.json"
_credentials_configured = False # Flag to track if setup was attempted

if "GOOGLE_CREDENTIALS_JSON" in st.secrets:
    logging.info("Found GOOGLE_CREDENTIALS_JSON in Streamlit Secrets. Setting up credentials file.")
    try:
        # 1. Read from secrets and log its representation
        credentials_json_content_from_secrets = st.secrets["GOOGLE_CREDENTIALS_JSON"]
        logging.info(f"Read {len(credentials_json_content_from_secrets)} characters from secret.")
        # Log first 500 chars using repr() to see hidden characters like \n explicitly
        logging.info(f"REPR of secret content (first 500 chars):\n>>>\n{repr(credentials_json_content_from_secrets[:500])}\n<<<")

        if not credentials_json_content_from_secrets.strip():
                logging.error("GOOGLE_CREDENTIALS_JSON secret is empty.")
                _credentials_configured = False
        else:
            # 2. Write the file with potential cleaning
            file_written_successfully = False
            try:
                # --- START CLEANING ATTEMPT ---
                cleaned_content = credentials_json_content_from_secrets
                try:
                    # Attempt to parse to find the private key and clean it specifically
                    temp_data = json.loads(credentials_json_content_from_secrets)
                    if 'private_key' in temp_data and isinstance(temp_data['private_key'], str):
                        original_pk = temp_data['private_key']
                        cleaned_pk = original_pk.replace('\r\n', '\n').replace('\r', '\n').replace('\\n', '\n')
                        if cleaned_pk != original_pk:
                            logging.warning("Attempted to clean '\\r' or incorrectly escaped '\\n' characters from private_key string.")
                            temp_data['private_key'] = cleaned_pk
                            cleaned_content = json.dumps(temp_data, indent=2)
                        else:
                            cleaned_content = credentials_json_content_from_secrets
                    else:
                        logging.warning("Could not find 'private_key' field (or it's not a string) in parsed secret data for cleaning.")
                        cleaned_content = credentials_json_content_from_secrets
                except json.JSONDecodeError:
                    logging.warning("Initial parse for targeted cleaning failed. Trying global replace on raw string (less safe).")
                    cleaned_content = credentials_json_content_from_secrets.replace('\r\n', '\n').replace('\r', '\n').replace('\\n', '\n')
                # --- END CLEANING ATTEMPT ---

                with open(CREDENTIALS_FILENAME, "w", encoding='utf-8') as f:
                    f.write(cleaned_content)
                logging.info(f"Successfully wrote potentially cleaned credentials to {CREDENTIALS_FILENAME} using UTF-8 encoding.")
                file_written_successfully = True
            except Exception as write_err:
                logging.error(f"CRITICAL Error during file writing (with cleaning attempt): {write_err}", exc_info=True)
                _credentials_configured = False # Ensure flag is false on write error

            # 3. If written, read back immediately and verify/parse
            if file_written_successfully:
                credentials_content_read_back = None
                try:
                    with open(CREDENTIALS_FILENAME, "r", encoding='utf-8') as f:
                        credentials_content_read_back = f.read()
                    logging.info(f"Successfully read back {len(credentials_content_read_back)} characters from {CREDENTIALS_FILENAME}.")
                    logging.info(f"REPR of read-back content (first 500 chars):\n>>>\n{repr(credentials_content_read_back[:500])}\n<<<")

                    # 4. Try parsing the read-back content manually using standard json library
                    try:
                        json.loads(credentials_content_read_back)
                        logging.info("Manual JSON parsing of read-back content SUCCEEDED.")
                        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_FILENAME
                        logging.info(f"GOOGLE_APPLICATION_CREDENTIALS set to point to: {CREDENTIALS_FILENAME}")
                        _credentials_configured = True # Mark configuration as successful ONLY here
                    except json.JSONDecodeError as parse_err:
                        logging.error(f"Manual JSON parsing of read-back content FAILED: {parse_err}", exc_info=True)
                        _credentials_configured = False # Parsing failed
                    except Exception as manual_parse_generic_err:
                        logging.error(f"Unexpected error during manual JSON parsing: {manual_parse_generic_err}", exc_info=True)
                        _credentials_configured = False

                except Exception as read_err:
                    logging.error(f"CRITICAL Error reading back credentials file {CREDENTIALS_FILENAME}: {read_err}", exc_info=True)
                    _credentials_configured = False

    except Exception as e:
        logging.error(f"CRITICAL Error reading secret: {e}", exc_info=True)
        _credentials_configured = False

elif "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
    logging.info("Using GOOGLE_APPLICATION_CREDENTIALS environment variable set externally.")
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and os.path.exists(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]):
        logging.info(f"External credentials file found at: {os.environ['GOOGLE_APPLICATION_CREDENTIALS']}")
        _credentials_configured = True
    else:
        logging.error(f"External GOOGLE_APPLICATION_CREDENTIALS path not found or not set: {os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')}")
        _credentials_configured = False

else:
    logging.warning("Vision API Credentials NOT found: Neither GOOGLE_CREDENTIALS_JSON secret nor GOOGLE_APPLICATION_CREDENTIALS env var is set.")
    _credentials_configured = False
# --- END: Runtime Credentials Setup ---


# --- PDF/Image Processing with Google Cloud Vision (Unchanged) ---
def extract_text_from_pdf(pdf_file_obj):
    """
    Extracts text from a PDF file object using Google Cloud Vision API OCR.
    Handles both text-based and image-based PDFs.
    Args:
        pdf_file_obj: A file-like object representing the PDF.
    Returns:
        str: The extracted text, with pages separated by double newlines.
             Returns an empty string "" if no text is found.
             Returns an error string starting with "Error:" if a critical failure occurs.
    """
    global _credentials_configured

    if not _credentials_configured:
        logging.error("Vision API credentials were not configured successfully during startup.")
        return "Error: Vision API authentication failed (Credentials setup failed)."

    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path or not os.path.exists(credentials_path):
        logging.error(f"Credentials check failed just before client init: GOOGLE_APPLICATION_CREDENTIALS path '{credentials_path}' not valid or file doesn't exist.")
        return "Error: Vision API credentials file missing or inaccessible at runtime."

    try:
        logging.info(f"Initializing Google Cloud Vision client using credentials file: {credentials_path}")
        client = vision.ImageAnnotatorClient()
        logging.info("Vision client initialized successfully.")

        pdf_file_obj.seek(0)
        content = pdf_file_obj.read()
        file_size = len(content)
        logging.info(f"Read {file_size} bytes from PDF stream.")

        if not content:
            logging.warning("PDF content is empty.")
            return ""

        mime_type = "application/pdf"
        input_config = vision.InputConfig(content=content, mime_type=mime_type)
        features = [vision.Feature(type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION)]
        # Explicitly setting language hint for Urdu/Arabic script
        image_context = vision.ImageContext(language_hints=["ur", "ar"]) # Added 'ur'
        request = vision.AnnotateFileRequest(
            input_config=input_config, features=features, image_context=image_context
        )

        logging.info("Sending request to Google Cloud Vision API (batch_annotate_files)...")
        response = client.batch_annotate_files(requests=[request])
        logging.info("Received response from Vision API.")

        if not response.responses:
            logging.error("Vision API returned an empty response list.")
            return "Error: Vision API returned no response."

        first_file_response = response.responses[0]

        if first_file_response.error.message:
            error_message = f"Vision API Error for file: {first_file_response.error.message}"
            logging.error(error_message)
            return f"Error: {error_message}"

        all_extracted_text = []
        if not first_file_response.responses:
            logging.warning("Vision API's AnnotateFileResponse contained an empty inner 'responses' list. No pages processed?")
            return ""

        for page_index, page_response in enumerate(first_file_response.responses):
            if page_response.error.message:
                logging.warning(f"  > Vision API Error for page {page_index + 1}: {page_response.error.message}")
                continue
            if page_response.full_text_annotation:
                page_text = page_response.full_text_annotation.text
                all_extracted_text.append(page_text)
            # else: # Optional logging
            #   logging.info(f"  > Page {page_index + 1} had no full_text_annotation.")

        extracted_text = "\n\n".join(all_extracted_text) # Use double newline as page separator

        if extracted_text:
            logging.info(f"Successfully extracted text from {len(all_extracted_text)} page(s) using Vision API. Total Length: {len(extracted_text)}")
            if not extracted_text.strip():
                logging.warning("Vision API processed pages, but extracted text is empty/whitespace after combining.")
                return ""
            return extracted_text
        else:
            logging.warning("Vision API response received, but no usable full_text_annotation found on any page.")
            return ""

    except Exception as e:
        logging.error(f"CRITICAL Error during Vision API interaction: {e}", exc_info=True)
        # Check for specific authentication errors if possible
        if "Could not automatically determine credentials" in str(e):
             return f"Error: Failed to process PDF with Vision API. Authentication failed: {e}"
        return f"Error: Failed to process PDF with Vision API. Exception: {e}"


# --- Gemini Processing (Unchanged from previous version) ---
def process_text_with_gemini(api_key: str, raw_text: str, rules_prompt: str, model_name: str):
    """
    Processes raw text using the specified Gemini API model based on provided rules.

    Args:
        api_key (str): The Gemini API key.
        raw_text (str): The raw text extracted from the PDF.
        rules_prompt (str): User-defined rules/instructions for Gemini.
        model_name (str): The specific Gemini model ID to use (e.g., "gemini-1.5-pro-latest").

    Returns:
        str: The processed text from Gemini. Returns empty string "" if raw_text is empty.
             Returns an error string starting with "Error:" if a failure occurs.
    """
    if not api_key:
        logging.error("Gemini API key is missing.")
        return "Error: Gemini API key is missing."

    if not raw_text or not raw_text.strip():
        logging.warning("Skipping Gemini call: No raw text provided.")
        return ""

    if not model_name:
        logging.error("Gemini model name is missing.")
        return "Error: Gemini model name not specified."

    try:
        genai.configure(api_key=api_key)
        logging.info(f"Initializing Gemini model: {model_name}")
        model = genai.GenerativeModel(model_name)

        full_prompt = f"""
        **Instructions:**
        {rules_prompt}

        **Text to Process (likely Urdu or Arabic script):**
        ---
        {raw_text}
        ---

        **Output:**
        Return ONLY the processed text according to the instructions. Do not add any introductory phrases like "Here is the processed text:". Ensure proper script formatting (e.g., Urdu, Arabic) and right-to-left presentation where appropriate.
        """

        logging.info(f"Sending request to Gemini model: {model_name}. Text length: {len(raw_text)}")
        # Consider adding safety settings if needed
        # safety_settings = [
        #     {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        #     {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        #     {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        #     {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        # ]
        # response = model.generate_content(full_prompt, safety_settings=safety_settings)
        response = model.generate_content(full_prompt)


        # Error handling for response (check for content blocking or empty response)
        if not response.parts:
            block_reason = None
            safety_ratings = None
            finish_reason = 'UNKNOWN' # Default finish reason

            if hasattr(response, 'prompt_feedback'):
                block_reason = getattr(response.prompt_feedback, 'block_reason', None)
                safety_ratings = getattr(response.prompt_feedback, 'safety_ratings', None)
                # Get finish reason if available (might indicate other issues like length)
                finish_reason = getattr(response.prompt_feedback, 'finish_reason', 'UNKNOWN')


            if block_reason:
                block_reason_msg = f"Content blocked by Gemini safety filters. Reason: {block_reason}"
                logging.error(f"Gemini request ({model_name}) blocked. Reason: {block_reason}. Ratings: {safety_ratings}")
                return f"Error: {block_reason_msg}"
            else:
                # Log other reasons for empty response if not blocked
                logging.warning(f"Gemini ({model_name}) returned no parts (empty response). Finish Reason: {finish_reason}. Safety Ratings: {safety_ratings}")
                # Return empty string, maybe the model genuinely produced nothing or hit another limit
                return ""

        # If parts exist, attempt to get text
        try:
             processed_text = response.text
        except ValueError as ve:
             # Handle cases where response.text might raise ValueError (e.g., function calls expected but not handled)
             logging.error(f"Gemini response ({model_name}) did not contain valid text. Potential function call or unexpected format? Error: {ve}", exc_info=True)
             # Check finish reason again, might provide clues
             finish_reason = getattr(getattr(response, 'prompt_feedback', None), 'finish_reason', 'UNKNOWN')
             return f"Error: Gemini response format issue. Finish Reason: {finish_reason}"


        logging.info(f"Successfully received response from Gemini ({model_name}). Processed text length: {len(processed_text)}")
        return processed_text

    except Exception as e:
        logging.error(f"Error interacting with Gemini API ({model_name}): {e}", exc_info=True)
        # Add more specific error messages if possible (e.g., API key invalid, quota exceeded)
        error_detail = str(e)
        if "API key not valid" in error_detail:
             return "Error: Invalid Gemini API Key."
        elif "Quota" in error_detail:
             return "Error: Gemini API Quota Exceeded."
        return f"Error: Failed to process text with Gemini ({model_name}). Details: {e}"


# --- Create SINGLE Word Document (Sets RTL/Font - Unchanged) ---
def create_word_document(processed_text: str):
    """
    Creates a single Word document (.docx) in memory containing the processed text.
    Sets paragraph alignment to right and text direction to RTL for Arabic/Urdu.
    Uses Arial font for complex scripts. Handles splitting text into paragraphs.

    Args:
        processed_text (str): The text to put into the document.

    Returns:
        io.BytesIO: A BytesIO stream containing the Word document data, or None on critical error.
                    Returns stream with placeholder if processed_text is empty.
    """
    try:
        document = Document()
        # --- Apply Formatting to Normal Style ---
        style = document.styles['Normal']
        font = style.font
        font.name = 'Arial' # Recommended for broad compatibility
        font.rtl = True # Enable RTL for the style's font

        # Set complex script font using oxml
        style_element = style.element
        rpr = style_element.xpath('.//w:rPr')
        if not rpr:
            rpr = OxmlElement('w:rPr')
            style_element.append(rpr)
        else:
            rpr = rpr[0]

        font_name_element = rpr.find(qn('w:rFonts'))
        if font_name_element is None:
            font_name_element = OxmlElement('w:rFonts')
            rpr.append(font_name_element)
        font_name_element.set(qn('w:cs'), 'Arial') # Set Complex Script font

        # Set paragraph format defaults for Normal style
        paragraph_format = style.paragraph_format
        paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        paragraph_format.right_to_left = True
        # --- End Style Formatting ---

        if processed_text and processed_text.strip():
            # Split text into paragraphs based on newlines
            lines = processed_text.strip().split('\n')
            for line in lines:
                if line.strip(): # Avoid adding empty paragraphs
                    # Add paragraph - it inherits style defaults (RTL, font, alignment)
                    paragraph = document.add_paragraph(line.strip())
                    # Redundant explicit setting (safe fallback, but style should handle it)
                    # paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    # paragraph.paragraph_format.right_to_left = True
                    # for run in paragraph.runs:
                    #     run.font.rtl = True
                    #     run.font.complex_script = True
        else:
            # Handle empty or whitespace-only content
            empty_msg = "[No text extracted or processed for this file]"
            paragraph = document.add_paragraph(empty_msg)
            paragraph.italic = True # Make it visually distinct
            # Ensure formatting is applied even for the placeholder via the style

        # Save document to a BytesIO stream
        doc_stream = io.BytesIO()
        document.save(doc_stream)
        doc_stream.seek(0)  # Rewind the stream to the beginning for reading
        logging.info("Successfully created single Word document in memory.")
        return doc_stream

    except Exception as e:
        logging.error(f"Error creating single Word document: {e}", exc_info=True)
        return None # Indicate failure to create the document stream


# --- Merging Function using docxcompose (Restored/Kept) ---
def merge_word_documents(doc_streams_data: list[tuple[str, io.BytesIO]]):
    """
    Merges multiple Word documents (provided as BytesIO streams) into one single document
    by direct concatenation without adding separators. Uses docxcompose library.

    Args:
        doc_streams_data (list[tuple[str, io.BytesIO]]): A list of tuples,
            where each tuple is (original_filename_str, word_doc_bytes_io_obj).

    Returns:
        io.BytesIO: A BytesIO stream containing the final merged Word document,
                    or None on error or if input list is empty.
    """
    if not doc_streams_data:
        logging.warning("No document streams provided for merging.")
        return None

    try:
        # Initialize Composer with the first document
        first_filename, first_stream = doc_streams_data[0]
        if not first_stream or not hasattr(first_stream, 'seek'):
             logging.error(f"Invalid stream provided for the first document: {first_filename}")
             return None
        first_stream.seek(0)
        try:
            master_doc = Document(first_stream)
        except Exception as load_err:
             logging.error(f"Failed to load base document '{first_filename}' with python-docx: {load_err}", exc_info=True)
             return None

        logging.info(f"Loaded base document from '{first_filename}'.")
        composer = Composer(master_doc)
        logging.info(f"Initialized merger with base document.")

        # Append remaining documents
        for i in range(1, len(doc_streams_data)):
            filename, stream = doc_streams_data[i]
            if not stream or not hasattr(stream, 'seek'):
                 logging.warning(f"Skipping invalid stream for document: {filename}")
                 continue # Skip this file
            stream.seek(0)
            logging.info(f"Merging content directly from '{filename}'...")
            try:
                 sub_doc = Document(stream)
                 composer.append(sub_doc)
                 logging.info(f"Successfully appended content from '{filename}'.")
            except Exception as append_err:
                 logging.warning(f"Failed to append document '{filename}': {append_err}. Skipping.", exc_info=True)
                 # Continue with the next file

        # Save the final merged document
        merged_stream = io.BytesIO()
        composer.save(merged_stream)
        merged_stream.seek(0)
        logging.info(f"Successfully merged {len(doc_streams_data)} documents (or fewer if errors occurred) by concatenation.")
        return merged_stream

    except Exception as e:
        logging.error(f"Error merging Word documents using docxcompose: {e}", exc_info=True)
        return None

# --- NEW: Splitting Function ---
def split_word_document(merged_doc_buffer: io.BytesIO, paragraphs_per_split: int = 75):
    """
    Splits a large Word document (from a BytesIO buffer) into smaller documents,
    each containing approximately `paragraphs_per_split` paragraphs (and associated tables).
    Attempts to preserve basic RTL and font settings.

    Args:
        merged_doc_buffer (io.BytesIO): Buffer containing the merged Word document.
        paragraphs_per_split (int): Target number of paragraphs per split file.
                                     This is an approximation for page count.

    Returns:
        list[dict]: A list of dictionaries, where each dict is
                    {'filename': 'split_part_N.docx', 'buffer': BytesIO_obj}
                    Returns an empty list if input is invalid or splitting fails.
    """
    if not merged_doc_buffer or not hasattr(merged_doc_buffer, 'seek'):
        logging.error("Invalid or empty buffer provided for splitting.")
        return []

    merged_doc_buffer.seek(0)
    try:
        source_doc = Document(merged_doc_buffer)
        logging.info(f"Loaded merged document for splitting. Found {len(source_doc.paragraphs)} paragraphs total (approx).")
    except Exception as e:
        logging.error(f"Failed to load merged document from buffer for splitting: {e}", exc_info=True)
        return []

    split_results = []
    current_split_doc = None
    current_paragraph_count = 0
    split_file_index = 0

    # --- Helper to create a new document and apply base styles ---
    def create_new_split_document():
        new_doc = Document()
        # Apply basic RTL/Font settings to the 'Normal' style of the new doc
        try:
            style = new_doc.styles['Normal']
            font = style.font
            font.name = 'Arial'
            font.rtl = True

            style_element = style.element
            rpr = style_element.xpath('.//w:rPr')
            if not rpr: rpr = OxmlElement('w:rPr'); style_element.append(rpr)
            else: rpr = rpr[0]

            font_name_element = rpr.find(qn('w:rFonts'))
            if font_name_element is None: font_name_element = OxmlElement('w:rFonts'); rpr.append(font_name_element)
            font_name_element.set(qn('w:cs'), 'Arial')

            paragraph_format = style.paragraph_format
            paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            paragraph_format.right_to_left = True
            logging.info(f"Applied base RTL/Font style to new split document {split_file_index + 1}")
        except Exception as style_err:
            logging.warning(f"Could not apply base styles to new split document {split_file_index + 1}: {style_err}")
        return new_doc
    # --- End Helper ---

    # Iterate through block-level items (paragraphs and tables) in the source document body
    # Using document.element.body directly to access underlying XML elements
    for block in source_doc.element.body:
        if current_split_doc is None:
            current_split_doc = create_new_split_document()

        # Check if the block is a paragraph ('w:p') or a table ('w:tbl')
        is_paragraph = block.tag.endswith('p')
        is_table = block.tag.endswith('tbl')

        if is_paragraph or is_table:
            # Create a deep copy of the element to add to the new document
            # This avoids modifying the source document and potential issues with shared objects
            try:
                 new_element = copy.deepcopy(block)
                 current_split_doc.element.body.append(new_element)
            except Exception as copy_err:
                 logging.warning(f"Failed to copy element (type: {block.tag}) to split doc {split_file_index + 1}: {copy_err}. Skipping element.")
                 continue # Skip this element

            # Increment count only for paragraphs to control splitting
            if is_paragraph:
                current_paragraph_count += 1

            # Check if the split point is reached (based on paragraph count)
            if current_paragraph_count >= paragraphs_per_split:
                # Save the current split document to a buffer
                try:
                    split_buffer = io.BytesIO()
                    current_split_doc.save(split_buffer)
                    split_buffer.seek(0)
                    split_filename = f"split_part_{split_file_index + 1}.docx"
                    split_results.append({'filename': split_filename, 'buffer': split_buffer})
                    logging.info(f"Saved split file: {split_filename} ({current_paragraph_count} paragraphs included)")

                    # Reset for the next split file
                    split_file_index += 1
                    current_split_doc = None # Signal to create a new one
                    current_paragraph_count = 0
                except Exception as save_err:
                    logging.error(f"Failed to save split document part {split_file_index + 1}: {save_err}", exc_info=True)
                    # Reset anyway to avoid adding more to a failed doc
                    current_split_doc = None
                    current_paragraph_count = 0


    # Save any remaining content in the last split document
    if current_split_doc is not None and current_paragraph_count > 0:
        try:
            split_buffer = io.BytesIO()
            current_split_doc.save(split_buffer)
            split_buffer.seek(0)
            split_filename = f"split_part_{split_file_index + 1}.docx"
            split_results.append({'filename': split_filename, 'buffer': split_buffer})
            logging.info(f"Saved final split file: {split_filename} ({current_paragraph_count} paragraphs included)")
        except Exception as save_err:
             logging.error(f"Failed to save final split document part {split_file_index + 1}: {save_err}", exc_info=True)

    logging.info(f"Splitting complete. Generated {len(split_results)} split document(s).")
    return split_results
