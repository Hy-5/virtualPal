import requests
from newspaper import Article
from transformers import pipeline
import json
import os
from datetime import datetime, timedelta
import logging
import fcntl

# logs config
log_file = '{lognewsfetcher.log path}'
logging.basicConfig(filename=log_file, level=logging.INFO, format='%(asctime)s - %(message)s')

# GNews API key
gnews_api_key = 'API_KEY_HERE'

# Directory to save summaries
summary_dir = 'art_summaries'
processed_urls_file = 'alreadyprocessed_urls.json'
lock_file_path = '/tmp/newsfetcher.lock'

if not os.path.exists(summary_dir):
    os.makedirs(summary_dir)

# Load processed URLs
def load_processed_urls():
    if os.path.exists(processed_urls_file):
        with open(processed_urls_file, 'r') as f:
            return set(json.load(f))
    return set()

# Save processed URLs
def save_processed_urls(processed_urls):
    with open(processed_urls_file, 'w') as f:
        json.dump(list(processed_urls), f)

# Check profile for interests
def read_interests_from_profile(profile_path='profile.txt'):
    try:
        with open(profile_path, 'r') as file:
            lines = file.readlines()
            for line in lines:
                if line.startswith('Likes/Interests :'):
                    interests = line.strip().split(': ')[1].strip().split(', ')
                    if interests[0] != 'Unknown':
                        return interests
    except FileNotFoundError:
        return []
    return []

# Fetch news articles related to interests using GNews
def fetch_news(api_key, query, num_articles=6):
    url = f'https://gnews.io/api/v4/search?q={query}&lang=en&max={num_articles}&apikey={api_key}'
    response = requests.get(url)
    articles = response.json().get('articles', [])
    return articles

# Function to extract article text
def extract_article_text(url):
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text
    except Exception as e:
        logging.error(f'Error downloading article at URL {url}: {e}')
        return None

# Summarize text from article | 0 if server is using GPU acceleration (MUCH faster), 1 if CPU
def summarize_text(text, max_summary_length=250):
    summarizer = pipeline('summarization', model="facebook/bart-large-cnn", device=0)  # Set device to 0 for GPU
    input_length = len(text.split())
    max_len = min(130, max(30, input_length // 2))  # Ensure max_length is at least 30 and at most 130

    # If the input text is too long, break it into smaller chunks | fixing processing errors
    chunk_size = 512  # Adjust this based on your model's token limit
    text_chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    summaries = []
    try:
        for chunk in text_chunks:
            chunk_input_length = len(chunk.split())
            chunk_max_len = min(130, max(30, chunk_input_length // 2))  # Dynamically adjust max_length for each chunk
            logging.info(f'Summarizing text (length: {chunk_input_length} words, max_length: {chunk_max_len})')  # Debugging log
            chunk_summary = summarizer(chunk, max_length=chunk_max_len, min_length=30, do_sample=False)
            summaries.append(chunk_summary[0]['summary_text'])

        combined_summary = ' '.join(summaries).strip()

        # Truncate the combined summary if it exceeds max_summary_length
        summary_words = combined_summary.split()
        if len(summary_words) > max_summary_length:
            combined_summary = ' '.join(summary_words[:max_summary_length])

        return combined_summary
    except Exception as e:
        logging.error(f'Error during summarization: {e}')
        return ""

# Main function to fetch, summarize, and save news articles
def main():
    processed_urls = load_processed_urls()
    interests = read_interests_from_profile()
    summaries = []

    if not interests or len(interests) < 3:
        interests = (interests if interests else []) + ['pop culture'] * (3 - len(interests))

    for interest in interests[:3]:  # Limit number of interests to fetch up to 3 interests - increase after srever upgrade
        articles = fetch_news(gnews_api_key, interest)
        for article in articles:  # Fetch all articles and process them
            title = article['title']
            url = article['url']
            if url in processed_urls:
                logging.info(f'Skipping article: {title}')
                continue
            text = extract_article_text(url)
            if not text or len(text.split()) < 50:  # Ensure the text is sufficiently long for summarization
                logging.info(f'Skipping short article: {title}')
                continue
            summary = summarize_text(text)
            if summary and any(interest.lower() in summary.lower() for interest in interests):  # Filter summaries
                summaries.append({'title': title, 'url': url, 'summary': summary})
                processed_urls.add(url)

    save_processed_urls(processed_urls)

    with open(os.path.join(summary_dir, 'summaries.json'), 'w') as f:
        json.dump(summaries, f, indent=4)

    logging.info("Completed fetching and summarizing news articles.")
    exit(0)

if __name__ == '__main__':
    # Clear previous log file content
    open(log_file, 'w').close()

    # Lock file mechanism to prevent multiple instances
    with open(lock_file_path, 'w') as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            logging.info("Acquired lock, starting news fetcher.")
            main()
        except IOError:
            logging.info("Could not acquire lock, another instance is running.")

