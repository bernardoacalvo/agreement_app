import streamlit as st
import json
import dropbox
import requests
from io import BytesIO
from PIL import Image


APP_KEY = st.secrets['DROPBOX_APP_KEY']
APP_SECRET = st.secrets['DROPBOX_APP_SECRET']
REDIRECT_URI = 'https://mep-agreement.streamlit.app/'

DROPBOX_AUTH_URL = (f"https://www.dropbox.com/oauth2/authorize?client_id={APP_KEY}"
        f"&response_type=code&redirect_uri={REDIRECT_URI}"
        "&token_access_type=offline")

RESULTS_PATH = "/{}.json"
CONTENT_TIME_EVALUATORS = ['bernardo', 'david', 'eric']

if 'page' not in st.session_state:
    st.session_state.page = 'auth'
if 'current_evaluator' not in st.session_state:
    st.session_state.current_evaluator = None
if 'step' not in st.session_state:
    st.session_state.step = 0
if 'results' not in st.session_state:
    st.session_state.results = {}
if 'similar_response' not in st.session_state:
    st.session_state.similar_response = None
if 'article_response' not in st.session_state:
    st.session_state.article_response = None
if 'dbx' not in st.session_state:
    st.session_state.dbx = None
if 'auth_code' not in st.session_state:
    st.session_state.auth_code = None
if 'refresh_token' not in st.session_state:
    st.session_state.refresh_token = None


def fetch_tokens(auth_code):
    token_url = "https://api.dropboxapi.com/oauth2/token"
    data = {
        "code": auth_code,
        "grant_type": "authorization_code",
        "client_id": APP_KEY,
        "client_secret": APP_SECRET,
        "redirect_uri": REDIRECT_URI,
    }
    response = requests.post(token_url, data=data)
    if response.status_code == 200:
        return response.json()
    else:
        st.error("Failed to authenticate. Please check your authorization code.")
        return None

def refresh_access_token(refresh_token):
    token_url = "https://api.dropboxapi.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": APP_KEY,
        "client_secret": APP_SECRET,
    }
    response = requests.post(token_url, data=data)
    if response.status_code == 200:
        return response.json()
    else:
        st.error("Failed to refresh token.")
        return None
    
def authenticate_dropbox():
    if st.session_state.auth_code:
        tokens = fetch_tokens(st.session_state.auth_code)
        if tokens:
            access_token = tokens.get('access_token')
            st.session_state.refresh_token = tokens.get('refresh_token')
            st.session_state.dbx = dropbox.Dropbox(access_token)
            st.session_state.page = 'main'
    else:
        st.error("Please insert a code.")

def refresh_token():
    if st.session_state.refresh_token:
        tokens = refresh_access_token(st.session_state.refresh_token)
        if tokens:
            st.session_state.dbx = dropbox.Dropbox(tokens.get('access_token'))

def handle_token():
    if st.session_state.dbx:
        try: 
            st.session_state.dbx.users_get_current_account()
        except dropbox.exceptions.AuthError:
            refresh_token()


handle_token()                  # check if access token needs to be refreshed

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
    st.session_state.step = 0
    st.session_state.results = {}
    st.session_state.total_steps = total_samples
    st.session_state.page = 'instructions'

def get_evaluation_step(evaluator_id, eval_type, step):
    if eval_type == 'general':
        evaluator_samples = general_evaluators_samples.get(evaluator_id, [])
        samples = general_samples
    else:       # granularity
        evaluator_samples = granularity_evaluators_samples.get(evaluator_id, [])
        samples = granularity_samples

    sample_id = evaluator_samples[step]
    sample_data = samples[sample_id]

    return {
        'sample_id': sample_id,
        'text': sample_data[0],
        'key': sample_data[1],
        'image_path': sample_data[2] if evaluator_id in evaluators_images[eval_type] else None,
        'ground_truth': sample_data[3],
        'article': sample_data[4] if evaluator_id in CONTENT_TIME_EVALUATORS else None,
        'prediction': sample_data[6],
    }

def set_similar_response(response, sample_id):
    st.session_state.similar_response = response
    check_and_proceed(sample_id)

def set_article_response(response, sample_id):
    st.session_state.article_response = response
    check_and_proceed(sample_id)

def check_and_proceed(sample_id):
    if st.session_state.similar_response is not None and (
            st.session_state.current_evaluator not in CONTENT_TIME_EVALUATORS or st.session_state.article_response is not None):
        next_step(sample_id)

def next_step(sample_id):
    st.session_state.results[sample_id] = {
        'similar_response': st.session_state.similar_response,
        'article_response': st.session_state.article_response
    }

    st.session_state.similar_response = None
    st.session_state.article_response = None

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

@st.cache_data
def dropbox_load_image(path):
    try:
        metadata, res = st.session_state.dbx.files_download(path)
        image_content = res.content
        image = Image.open(BytesIO(image_content))
        return image
    except dropbox.exceptions.ApiError as err:
        return None

# ----- pages -----

def auth_page():
    st.title("Dropbox Authentication")
    st.markdown(f'<a href="{DROPBOX_AUTH_URL}" target="_self">Click here to authorize the app with Dropbox</a>', unsafe_allow_html=True)
    st.write("Please check the URL and copy the code after 'code='.")
    st.text_input("Paste the authorization code here and click on the button.", key="auth_code")
    st.button("Submit Authorization Code", on_click=authenticate_dropbox, use_container_width=True, type='primary')
    st.write("**Note:** If you refresh the page, you may need a new authorization code.")


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
                 " The expected time for this evaluation is between 20 and 30 minutes. Some examples:")
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
                 " The expected time for this evaluation is between 10 and 15 minutes. Some examples:")
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

    if st.session_state.current_evaluator in CONTENT_TIME_EVALUATORS:
        st.markdown("<hr>", unsafe_allow_html=True)
        st.write("**CONTENT TIME EVALUATION**")
        st.write("Additionally, given the article link or, if unavailable, the article text itself, determine whether the news **CONTENT** refers to an OLD NEWS article, or RECENT NEWS article, or DON'T KNOW if can not be determined.")
    st.button("Start Evaluation", on_click=set_page, args=('evaluation',), use_container_width=True, type="primary")


def evaluation_page():
    curr_evaluator_id = st.session_state.current_evaluator
    step_number = st.session_state.step
    step = get_evaluation_step(curr_evaluator_id, st.session_state.eval_type, step_number)

    st.write(f"Evaluation step {step_number + 1}")

    sample_id = step["sample_id"]

    image_path = step["image_path"]
    if image_path:
        st.image(dropbox_load_image(image_path.lstrip(".")))

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

    # Content scope evaluation (only for some evaluators)
    key = step['key']
    if curr_evaluator_id in CONTENT_TIME_EVALUATORS and key != 'DATE':
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:24px;'><strong>Article:</strong></p>", unsafe_allow_html=True)
        article = step['article']
        if ".com" in article:
            st.markdown(f"<p style='font-size:18px;'><a href='{article}'>{article}</a></p>", unsafe_allow_html=True)
        else:
            st.markdown(f"<p style='font-size:18px;'>{article}</p>", unsafe_allow_html=True)

        col3, col4, col5 = st.columns(3)
        is_recent_events_source = int(sample_id.split("_")[0]) == 4
        with col3:
            add_text = "before 2024" if is_recent_events_source else "before 2017"
            st.button(f"Old News ({add_text})", on_click=set_article_response, args=(0, sample_id), key="old_news_button", use_container_width=True)
        with col4:
            st.button("Don't Know", on_click=set_article_response, args=(1, sample_id), key="dont_know_button", use_container_width=True)
        with col5:
            add_text = "after 2024 incl." if is_recent_events_source else "after 2017 incl."
            st.button(f"Recent News ({add_text})", on_click=set_article_response, args=(2, sample_id), key="recent_news_button", use_container_width=True)


def end_page():
    st.title("Evaluation Complete")
    evaluation_id = st.session_state.current_evaluator + '_' + st.session_state.eval_type
    success = save_results(evaluation_id, st.session_state.results)
    st.write("Thank you for completing the evaluation and contributing to my work :).")
    if success:
        st.write("Your responses have been recorded.")
    else:
        st.write("Something went wrong!")
        st.write("Copy the following JSON and send it to Bernardo. Thanks.")
        st.write(st.session_state.results)
    st.button("Back to Dashboard", on_click=set_page, args=('main',), use_container_width=True, type='primary')

def main():
    if st.session_state.page == 'auth':
        auth_page()
    elif st.session_state.page == 'main':
        main_page()
    elif st.session_state.page == 'instructions':
        instructions_page()
    elif st.session_state.page == 'evaluation':
        evaluation_page()
    elif st.session_state.page == 'end':
        end_page()


if __name__ == '__main__':
    main()
