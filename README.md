TikTok Activity Data Scraper

Overview :
TikTok Activity Data Scraper is a Python-based tool designed to scrape TikTok user activity data efficiently. By leveraging asynchronous scraping, the script retrieves data such as likes, comments, and interactions, and performs keyword analysis to identify significant terms in user activity. The output is stored in JSON format, making it easy to analyze and explore trends or patterns in TikTok user behavior.

Features :
Asynchronous Scraping: Built using asyncio and httpx for fast, non-blocking data retrieval. Able to scrape up to 300 posts per minute.
Comprehensive User Data: Extracts user activity, specifically looking at a user's liked posts.
Keyword Filtering: Applies custom logic to find key words within scraped data.
JSON Output: Saves results in JSON format for easy integration with other tools or systems.
Error Handling: Robust error handling to manage TikTok's dynamic web structure.

Getting Started :
Prerequisites -
Before running the scraper, make sure you have the following installed:
Python 3.x
httpx for asynchronous HTTP requests
parsel for HTML/XML data extraction
asyncio for asynchronous programming
nltk for word processing

Clone this repository to your local machine:
git clone https://github.com/SomethingObvious/tiktok-activity-data-scraper.git

Navigate to the project directory:
cd tiktok-activity-data-scraper

Run the script:
Within the myenv folder, run python tiktok_post_scraper.py 
Wait until the program completes scraping.
Then, run python post_data_collection.py 

post_data.json example : 
{
    "id": "7400543367504858373",
    "desc": "Cream Cheese Stuffed Everything Bagel ",
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
      "diggCount": 6917, #Favorited Count
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
      "bagel",
      "food tiktoks",
      "food tok",
      "Bagel Bread",
      "cheese",
      "Bagel Cream Cheese Sandwich",
      "Bagel Sandwich",
      "Food TikTok Recipes"
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
  
Contributing :
Feel free to submit issues or pull requests if you have suggestions for improvements or if you encounter any bugs.

Fork the repository :
Create your feature branch (git checkout -b feature/my-feature).
Commit your changes (git commit -m 'Add new feature').
Push to the branch (git push origin feature/my-feature).
Open a pull request.

License :
This project is licensed under the MIT License - see the LICENSE file for details.

Contact :
For questions or feedback, feel free to contact me via the GitHub repository.

