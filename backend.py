# backend.py (with Model Selection Parameter)

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

# --- NEW: Import docxcompose ---
from docxcompose.composer import Composer

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
        image_context = vision.ImageContext(language_hints=["ar"])
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
            #    logging.info(f"  > Page {page_index + 1} had no full_text_annotation.")

        extracted_text = "\n\n".join(all_extracted_text)

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
        return f"Error: Failed to process PDF with Vision API. Exception: {e}"


# --- Gemini Processing (MODIFIED) ---
# --- ADD model_name parameter ---
def process_text_with_gemini(api_key: str, raw_text: str, rules_prompt: str, model_name: str):
    """
    Processes raw text using the specified Gemini API model based on provided rules.

    Args:
        api_key (str): The Gemini API key.
        raw_text (str): The raw text extracted from the PDF.
        rules_prompt (str): User-defined rules/instructions for Gemini.
        model_name (str): The specific Gemini model ID to use (e.g., "gemini-1.5-flash-latest").

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

    # --- NEW: Check if model_name is provided ---
    if not model_name:
        logging.error("Gemini model name is missing.")
        return "Error: Gemini model name not specified."
    # ---

    try:
        genai.configure(api_key=api_key)
        # --- Use the PASSED model name ---
        logging.info(f"Initializing Gemini model: {model_name}")
        model = genai.GenerativeModel(model_name)
        # ---                               ---

        full_prompt = f"""
        **Instructions:**
        {rules_prompt}

        **Arabic Text to Process:**
        ---
        {raw_text}
        ---

        **Output:**
        Return ONLY the processed text according to the instructions. Do not add any introductory phrases like "Here is the processed text:". Ensure proper Arabic formatting and right-to-left presentation.
        """

        # --- Update logging to include the model name ---
        logging.info(f"Sending request to Gemini model: {model_name}. Text length: {len(raw_text)}")
        # ---
        response = model.generate_content(full_prompt)

        # Error handling for response remains the same
        if not response.parts:
            block_reason = None
            safety_ratings = None
            if hasattr(response, 'prompt_feedback'):
                 block_reason = getattr(response.prompt_feedback, 'block_reason', None)
                 safety_ratings = getattr(response.prompt_feedback, 'safety_ratings', None)

            if block_reason:
                block_reason_msg = f"Content blocked by Gemini safety filters. Reason: {block_reason}"
                logging.error(f"Gemini request ({model_name}) blocked. Reason: {block_reason}. Ratings: {safety_ratings}")
                return f"Error: {block_reason_msg}"
            else:
                finish_reason_obj = getattr(response, 'prompt_feedback', None)
                finish_reason = getattr(finish_reason_obj, 'finish_reason', 'UNKNOWN') if finish_reason_obj else 'UNKNOWN'
                logging.warning(f"Gemini ({model_name}) returned no parts (empty response). Finish Reason: {finish_reason}")
                return ""

        processed_text = response.text
        logging.info(f"Successfully received response from Gemini ({model_name}). Processed text length: {len(processed_text)}")
        return processed_text

    except Exception as e:
        logging.error(f"Error interacting with Gemini API ({model_name}): {e}", exc_info=True)
        return f"Error: Failed to process text with Gemini ({model_name}). Details: {e}"


# --- Create SINGLE Word Document (Unchanged) ---
def create_word_document(processed_text: str):
    """
    Creates a single Word document (.docx) in memory containing the processed text.
    Sets paragraph alignment to right and text direction to RTL for Arabic.
    Handles splitting text into paragraphs based on newlines.

    Args:
        processed_text (str): The text to put into the document.

    Returns:
        io.BytesIO: A BytesIO stream containing the Word document data, or None on critical error.
                    Returns stream with placeholder if processed_text is empty.
    """
    try:
        document = Document()
        # Set default font and RTL for Normal style (applied to new paragraphs)
        style = document.styles['Normal']
        font = style.font
        font.name = 'Arial'
        font.rtl = True # Set RTL on the style's font

        # Using qn allows setting the font for complex scripts (like Arabic)
        # Find or create the <w:rPr> element within the style definition
        style_element = style.element
        rpr_elements = style_element.xpath('.//w:rPr')
        if not rpr_elements:
            # If <w:rPr> doesn't exist, create it (very unlikely for Normal style)
            rpr = OxmlElement('w:rPr')
            style_element.append(rpr)
        else:
            rpr = rpr_elements[0]

        # Find or create the <w:rFonts> element within <w:rPr>
        font_name_element = rpr.find(qn('w:rFonts'))
        if font_name_element is None:
             font_name_element = OxmlElement('w:rFonts')
             rpr.append(font_name_element)
        # Set the complex script font attribute
        font_name_element.set(qn('w:cs'), 'Arial') # Complex Script font

        # Set default paragraph format to RTL for Normal style
        paragraph_format = style.paragraph_format
        paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        paragraph_format.right_to_left = True

        if processed_text and processed_text.strip():
            # Split text into paragraphs based on newlines
            lines = processed_text.strip().split('\n')
            for line in lines:
                if line.strip(): # Avoid adding empty paragraphs
                    # Add paragraph - it should inherit style defaults (RTL, font)
                    paragraph = document.add_paragraph(line.strip())
                    # Explicitly set format just in case (redundant but safe)
                    paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    paragraph.paragraph_format.right_to_left = True
                    # Explicitly set run font properties (redundant but safe)
                    for run in paragraph.runs:
                        run.font.name = 'Arial'
                        run.font.rtl = True
                        run.font.complex_script = True # Ensure complex script is handled
        else:
            # Handle empty or whitespace-only content
            empty_msg = "[No text extracted or processed for this file]"
            paragraph = document.add_paragraph(empty_msg)
            paragraph.italic = True # Make it visually distinct
            # Ensure formatting is applied even for the placeholder
            paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            paragraph.paragraph_format.right_to_left = True
            for run in paragraph.runs:
                 run.font.name = 'Arial'
                 run.font.rtl = True
                 run.font.complex_script = True


        # Save document to a BytesIO stream
        doc_stream = io.BytesIO()
        document.save(doc_stream)
        doc_stream.seek(0)  # Rewind the stream to the beginning for reading
        logging.info("Successfully created single Word document in memory.")
        return doc_stream

    except Exception as e:
        logging.error(f"Error creating single Word document: {e}", exc_info=True)
        return None # Indicate failure to create the document stream


# --- Merging Function using docxcompose (Unchanged) ---
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
        # --- Initialize Composer with the first document ---
        first_filename, first_stream = doc_streams_data[0]
        first_stream.seek(0)
        master_doc = Document(first_stream)
        logging.info(f"Loaded base document from '{first_filename}'.")
        composer = Composer(master_doc)
        logging.info(f"Initialized merger with base document.")

        # --- Append remaining documents ---
        for i in range(1, len(doc_streams_data)):
            filename, stream = doc_streams_data[i]
            stream.seek(0)
            logging.info(f"Merging content directly from '{filename}'...")
            sub_doc = Document(stream)
            composer.append(sub_doc)
            logging.info(f"Successfully appended content from '{filename}'.")

        # --- Save the final merged document ---
        merged_stream = io.BytesIO()
        composer.save(merged_stream)
        merged_stream.seek(0)
        logging.info(f"Successfully merged {len(doc_streams_data)} documents by concatenation.")
        return merged_stream

    except Exception as e:
        logging.error(f"Error merging Word documents using docxcompose: {e}", exc_info=True)
        return None
