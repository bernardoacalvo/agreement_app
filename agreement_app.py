import random
import streamlit as st
import json
import dropbox
import requests
from io import BytesIO
from PIL import Image


APP_KEY = st.secrets['DROPBOX_APP_KEY']
APP_SECRET = st.secrets['DROPBOX_APP_SECRET']
REFRESH_TOKEN = st.secrets['DROPBOX_APP_REFRESH_TOKEN']
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"

RESULTS_PATH = "/{}.json"

if 'page' not in st.session_state:
    st.session_state.page = 'main'
if 'current_evaluator' not in st.session_state:
    st.session_state.current_evaluator = None
if 'evaluator_samples' not in st.session_state:
    st.session_state.evaluator_samples = []
if 'curr_samples' not in st.session_state:
    st.session_state.curr_samples = {}
if 'step' not in st.session_state:
    st.session_state.step = 0
if 'results' not in st.session_state:
    st.session_state.results = {}
if 'similar_response' not in st.session_state:
    st.session_state.similar_response = None
if 'dbx' not in st.session_state:
    st.session_state.dbx = None


def refresh_access_token():
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": APP_KEY,
        "client_secret": APP_SECRET,
    }
    response = requests.post(TOKEN_URL, data=data)
    if response.status_code == 200:
        new_tokens = response.json()
        new_access_token = new_tokens.get("access_token")
        st.toast("Access token refreshed successfully.")
        return new_access_token
    else:
        st.error("Failed to refresh access token.")
        return None

def validate_token():
    try:
        st.session_state.dbx.users_get_current_account()
    except dropbox.exceptions.AuthError:
        # token expired
        access_token = refresh_access_token()
        if access_token:
            st.session_state.access_token = access_token
            st.session_state.dbx = dropbox.Dropbox(access_token)
        else:
            st.error("Could not refresh the token. Manual intervention required.")

def handle_dropbox_access_token():
    if 'access_token' not in st.session_state:
        st.session_state.access_token = refresh_access_token()
        st.session_state.dbx = dropbox.Dropbox(st.session_state.access_token)
    validate_token()


handle_dropbox_access_token()

def load_json_from_dropbox(path):
    try:
        _, res = st.session_state.dbx.files_download(path)
        return json.loads(res.content)
    except dropbox.exceptions.ApiError as err:
        st.error(f"Failed to download {path} from Dropbox: {err}")
        return {}

@st.cache_data
def load_data():
    evaluators_images = load_json_from_dropbox("/agreement/evaluators_images.json")
    general_evaluators_samples = load_json_from_dropbox("/agreement/general_evaluators_samples.json")
    granularity_evaluators_samples = load_json_from_dropbox("/agreement/granularity_evaluators_samples.json")
    general_samples = load_json_from_dropbox("/agreement/general_samples.json")
    granularity_samples = load_json_from_dropbox("/agreement/granularity_samples.json")
    return evaluators_images, general_evaluators_samples, granularity_evaluators_samples, general_samples, granularity_samples


if st.session_state.dbx:
    evaluators_images, general_evaluators_samples, granularity_evaluators_samples, general_samples, granularity_samples = load_data()

def set_page(page):
    st.session_state.page = page

def start_evaluation(evaluator, is_general, total_samples):
    st.session_state.current_evaluator = evaluator
    st.session_state.eval_type = 'general' if is_general else 'granularity'
    evaluator_samples = general_evaluators_samples.get(evaluator, []) if is_general else granularity_evaluators_samples.get(evaluator, [])
    random.seed(42)
    random.shuffle(evaluator_samples)
    st.session_state.evaluator_samples = evaluator_samples
    st.session_state.curr_samples = general_samples if is_general else granularity_samples
    st.session_state.step = 0
    st.session_state.results = {}
    st.session_state.total_steps = total_samples
    st.session_state.page = 'instructions'

def get_evaluation_step(evaluator_id, eval_type, step):
    sample_id = st.session_state.evaluator_samples[step]
    sample_data = st.session_state.curr_samples[sample_id]
    return {
        'sample_id': sample_id,
        'text': sample_data[0],
        'key': sample_data[1],
        'image_path': sample_data[2] if evaluator_id in evaluators_images[eval_type] else None,
        'ground_truth': sample_data[3],
        #'article': sample_data[4],
        'prediction': sample_data[5],
    }

def set_similar_response(response, sample_id):
    st.session_state.similar_response = response
    next_step(sample_id)

def next_step(sample_id):
    st.session_state.results[sample_id] = {
        'similar_response': st.session_state.similar_response,
    }

    st.session_state.similar_response = None

    if st.session_state.step + 1 < st.session_state.total_steps:
        st.session_state.step += 1
    else:
        set_page('end')

def save_results(evaluation_id, results):
    results_file_path = RESULTS_PATH.format(evaluation_id)
    json_data = json.dumps(results, indent=4)
    return dropbox_upload_file(results_file_path, json_data)

def is_evaluation_done(evaluation_id):
    results_file_path = RESULTS_PATH.format(evaluation_id)
    return dropbox_file_exists(results_file_path)

def dropbox_upload_file(path, json_data):
    try:
        st.session_state.dbx.files_upload(json_data.encode(), path, mode=dropbox.files.WriteMode.overwrite)
        return True
    except Exception:
        st.error('Failed to upload to Dropbox.')
        return False

def dropbox_file_exists(path):
    try:
        st.session_state.dbx.files_get_metadata(path)
        return True
    except Exception:
        return False

def dropbox_load_image(path):
    try:
        metadata, res = st.session_state.dbx.files_download(path)
        image_content = res.content
        image = Image.open(BytesIO(image_content))
        return image
    except dropbox.exceptions.ApiError as err:
        return None

# ----- pages -----

def main_page():
    st.empty()
    st.title("MEP Evaluation Dashboard")
    for evaluator in general_evaluators_samples:
        general_id = f"{evaluator}_general"
        total_samples = len(general_evaluators_samples[evaluator])
        button_text = f"**{evaluator.upper().replace('_', ' ')}** - General Evaluation ({total_samples} samples)"
        st.button(button_text, on_click=start_evaluation, args=(evaluator, True, total_samples), disabled=is_evaluation_done(general_id), use_container_width=True, type="primary")
    for evaluator in granularity_evaluators_samples:
        granularity_id = f"{evaluator}_granularity"
        total_samples = len(granularity_evaluators_samples[evaluator])
        button_text = f"**{evaluator.upper().replace('_', ' ')}** - Granularity Evaluation ({total_samples} samples)"
        st.button(button_text, on_click=start_evaluation, args=(evaluator, False, total_samples), disabled=is_evaluation_done(granularity_id), use_container_width=True, type="primary")


def instructions_page():
    st.title("Instructions")
    st.write("Please read the following instructions carefully before starting the evaluation.")
    if st.session_state.eval_type == 'general':
        st.write("In the general evaluation, you will be presented with a caption (and an image, for some evaluators), along with a prediction and a ground truth."
                 " The prediction represents the text generated by a model, and the ground truth pertains to events, locations, or dates present in the caption."
                 " Your task it to assess whether the prediction is semantically similar to the ground truth."
                 " Be restrict, however, if the prediction and ground truth differ in format they should be considered similar if they refer to the same entity."
                 " The expected time for this evaluation is between 5 and 15 minutes. Some examples:")
        st.markdown("<hr>", unsafe_allow_html=True)
        st.write("**EVENT**")
        st.markdown("<p style='font-size:24px;'>Mikel Astarloza crosses the finish line to win the 16th stage of the Tour de France</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:24px;'><strong>Prediction:</strong> Tour de France 2023</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:24px;'><strong>Ground Truth:</strong> the Tour de France</p>", unsafe_allow_html=True)
        st.write("**In this case, we would consider it NOT SIMILAR because, although the prediction correctly identifies the event, it states a year that is incorrect.**")
        st.markdown("<hr>", unsafe_allow_html=True)
        st.write("**LOCATION**")
        st.markdown("<p style='font-size:24px;'>A Pakistani boy cools off in a park in Multan as temperatures reached record highs in a continuing heatwave</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:24px;'><strong>Prediction:</strong> Pakistan</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:24px;'><strong>Ground Truth:</strong> Multan</p>", unsafe_allow_html=True)
        st.write("**In this case, we would consider it NOT SIMILAR because, although the Multan city is in Pakistan, the ground truth specifies the city, not the country.**")
        st.markdown("<hr>", unsafe_allow_html=True)
        st.write("**DATE**")
        st.markdown("<p style='font-size:24px;'>The new reality the Nasdaq stock exchange s computerised billboard advertises the flotation of Facebook May 2012</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:24px;'><strong>Prediction:</strong> May 18, 2012</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:24px;'><strong>Ground Truth:</strong> May 2012</p>", unsafe_allow_html=True)
        st.write("**In this case, we would consider it SIMILAR because, the prediction date is included in the ground truth date. If the ground truth were \"17/5/2012\", it would be NOT SIMILAR, only because it fails by a day.**")
    else:       # granularity
        st.write("In the granularity evaluation, you will be presented with a caption (and an image, for some evaluators), along with a prediction and a ground truth."
                 " The prediction represents the text generated by a model, and the ground truth pertains to locations (cities or countries) derived from the caption."
                 " Your task it to assess whether the location prediction is semantically similar to the ground truth."
                 " Be restrict, however, if the prediction and ground truth differ in format they should be considered similar if they refer to the same entity."
                 " The expected time for this evaluation is between 5 and 15 minutes. Some examples:")
        st.markdown("<hr>", unsafe_allow_html=True)
        st.write("**CITY**")
        st.markdown("<p style='font-size:24px;'>Kate stopped at a table of toquetopped kids during a visit to a Taste of British Columbia festival at the Mission Hill Winery in Kelowna BC</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:24px;'><strong>Prediction:</strong> Victoria</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:24px;'><strong>Ground Truth:</strong> Kelowna</p>", unsafe_allow_html=True)
        st.write("**In this case, we would consider it NOT SIMILAR because, although the Victoria city is in Canada, the ground truth specifies the Kelowna city.**")
        st.markdown("<hr>", unsafe_allow_html=True)
        st.write("**COUNTRY**")
        st.markdown("<p style='font-size:24px;'>Attack of the vapours Kevin McKenna smokes an electronic cigarette in a pub in Glasgow</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:24px;'><strong>Prediction:</strong> England</p>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:24px;'><strong>Ground Truth:</strong> United Kingdom</p>", unsafe_allow_html=True)
        st.write("**In this case, we would consider it NOT SIMILAR because, although England is in the UK, the event happened in Glasgow, Scotland, not England. Either Scotland or UK as prediction would be considered SIMILAR.**")
        st.write("**Note: If the ground truth is a country, and the prediction is a city in that country, that is considered NOT SIMILAR because, both need to at least refer to the same granularity level.**")

    st.button("Start Evaluation", on_click=set_page, args=('evaluation',), use_container_width=True, type="primary")


def evaluation_page():
    curr_evaluator_id = st.session_state.current_evaluator
    step_number = st.session_state.step
    step = get_evaluation_step(curr_evaluator_id, st.session_state.eval_type, step_number)

    st.write(f"Evaluation step {step_number + 1}")

    sample_id = step["sample_id"]

    image_path = step["image_path"]
    if image_path:
        image = dropbox_load_image(image_path.lstrip("."))
        st.image(image)
        del image

    ground_truth = step['ground_truth']
    text = step['text']
    if st.session_state.eval_type == 'general':
        text = text.replace(ground_truth, f"<strong style='font-size:24px;'>{ground_truth}</strong>")
    st.markdown(f"<p style='font-size:24px;'>{text}</p>", unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(f"<p style='font-size:24px;'><strong>Prediction:</strong> {step['prediction']}</p>", unsafe_allow_html=True)
    st.markdown(f"<p style='font-size:24px;'><strong>Ground Truth:</strong> {ground_truth}</p>", unsafe_allow_html=True)

    st.markdown("""
            <style>
            .custom-button {
                font-size: 20px !important;
                padding: 12px 24px !important;
                width: 100%;
            }
            .full-width-column .stButton button {
                width: 100% !important;
            }
            </style>
            """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.button("NOT Similar", on_click=set_similar_response, args=(False, sample_id), key="not_similar_button", use_container_width=True)
    with col2:
        st.button("Similar", on_click=set_similar_response, args=(True, sample_id), key="similar_button", use_container_width=True)

def end_page():
    st.title("Evaluation Complete")
    evaluation_id = st.session_state.current_evaluator + '_' + st.session_state.eval_type
    success = save_results(evaluation_id, st.session_state.results)
    st.write("Thank you for completing the evaluation and contributing to my work :).")
    if success:
        st.write("Your responses have been saved.")
    else:
        st.write("Something went wrong!")
        st.write("Copy the following JSON and send it to Bernardo. Thanks.")
        st.write(st.session_state.results)
    # clear memory
    for key in ['evaluator_samples', 'curr_samples', 'results']:
        if key in st.session_state:
            del st.session_state[key]
    st.button("Back to Dashboard", on_click=set_page, args=('main',), use_container_width=True, type='primary')

def main():
    if st.session_state.page == 'main':
        main_page()
    elif st.session_state.page == 'instructions':
        instructions_page()
    elif st.session_state.page == 'evaluation':
        evaluation_page()
    elif st.session_state.page == 'end':
        end_page()


if __name__ == '__main__':
    main()
