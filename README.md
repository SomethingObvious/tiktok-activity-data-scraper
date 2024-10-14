# TikTok Activity Data Scraper

## Overview
The **TikTok Activity Data Scraper** is a Python-based tool designed for efficient scraping of TikTok user activity data. By leveraging asynchronous scraping, this script retrieves data such as likes, comments, and interactions, and performs keyword analysis to identify significant terms in user activity. The output is stored in JSON format, making it easy to analyze and explore trends or patterns in TikTok user behavior.

## Features
- **Asynchronous Scraping:** Built using `asyncio` and `httpx` for fast, non-blocking data retrieval, capable of scraping up to 300 posts per minute.
- **Comprehensive User Data:** Extracts user activity, specifically focusing on a user's liked posts.
- **Keyword Filtering:** Applies custom logic to identify key words within scraped data.
- **JSON Output:** Saves results in JSON format for easy integration with other tools or systems.
- **Error Handling:** Robust error handling to manage TikTok's dynamic web structure.

## Getting Started

### Prerequisites
Before running the scraper, ensure you have the following installed:
- **Python 3.x**
- **httpx** for asynchronous HTTP requests
- **parsel** for HTML/XML data extraction
- **asyncio** for asynchronous programming
- **nltk** for word processing

### Installation
1. **Clone this repository to your local machine:**
   ```bash
   git clone https://github.com/SomethingObvious/tiktok-activity-data-scraper.git
   ```
   
2. **Navigate to the project directory:**
   ```bash
   cd tiktok-activity-data-scraper
   ```

### Running the Scraper
1. **Run the script:**  
   Inside the `myenv` folder, execute:
   ```bash
   python tiktok_post_scraper.py
   ```
   Wait until the program completes scraping. Raw post data will be saved in the `scraper_output` folder as `post_data.json`, which is located under the `scraper_data` folder.

2. **Post Data Collection:**  
   Run the following script within the `post_processing` folder:
   ```bash
   python post_data_collection.py
   ```
   The collected post data will be available as `.txt` or `.json` files in the `post_processing` folder.

3. **Data Processing:**  
   For additional insights into the post data, such as recurring themes within hashtags and how hashtags relate to each other via WordNet synsets, run:
   ```bash
   python data_processor.py
   ```
   Processed insights will be available in the `processed_data` folder as `.txt` and `.json`.

4. **Update Synsets:**  
   To update the `custom_synsets.json` file, execute:
   ```bash
   python synset_updater.py
   ```

5. **Check Synset Assignment:**  
   Run the following script to check if a string already has an assigned synset via WordNet:
   ```bash
   python wordnet_search.py
   ```

### Example of `post_data.json`
```json
{
  "id": "7400543367504858373",
  "desc": "Cream Cheese Stuffed Everything Bagel",
  "createTime": "1723073280",
  "video": {
    "duration": 50
  },
  "author": {
    "id": "106392206474711040",
    "uniqueId": "genericauthor",
    "nickname": "Alice Bob",
    "verified": true
  },
  "stats": {
    "diggCount": 6917,  // Favorited Count
    "shareCount": 1127,
    "commentCount": 72,
    "playCount": 87200,
    "collectCount": "700"
  },
  "locationCreated": "US",
  "diversificationLabels": [
    "Cooking",
    "Food & Drink",
    "Lifestyle"
  ],
  "suggestedWords": [
    "cream cheese",
    "Cream Cheese Bagel",
    "bagel"
  ],
  "contents": [
    {
      "textExtra": [
        {
          "hashtagName": "pedalboards"
        },
        {
          "hashtagName": "guitarpedals"
        },
        {
          "hashtagName": "olympics"
        }
      ]
    }
  ],
  "isFavorite": false
}
```

## Contributing
Feel free to submit issues or pull requests if you have suggestions for improvements or encounter any bugs.

### Fork the Repository
1. Fork the repository.
2. Create your feature branch:
   ```bash
   git checkout -b feature/my-feature
   ```
3. Commit your changes:
   ```bash
   git commit -m 'Add new feature'
   ```
4. Push to the branch:
   ```bash
   git push origin feature/my-feature
   ```
5. Open a pull request.

## Contact
For questions or feedback, feel free to contact me via the GitHub repository.
