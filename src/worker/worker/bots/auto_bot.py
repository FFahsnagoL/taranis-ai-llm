from .base_bot import BaseBot
from worker.log import logger
from worker.bot_api import BotApi
from worker.config import Config

import datetime
import time
import uuid

class AutoBot(BaseBot):
    def __init__(self):
        super().__init__()
        self.type = "AUTO_BOT"
        self.name = "Auto Bot"
        self.description = "Bot to analyze news items' content"
        self.bot_api = BotApi(Config.AUTO_API_ENDPOINT)

    def execute(self, parameters: dict | None = None)-> dict:

        if not parameters:
            parameters = {}
        if not (data := self.get_stories(parameters)):
            return {"message": "No new stories found"}
            

        self.bot_api.api_url = parameters.get("BOT_ENDPOINT", Config.AUTO_API_ENDPOINT)

        logger.info(f"Analyzing relevance for {len(data)} news items")

        # Process each story
        if relevance_results := self.analyze_news(data):
            logger.debug(f"Analyzing relevance for {len(data)} news items")
            self.publish_news(relevance_results)
            return {"message": "Relevance analysis complete"}

        return {"message": "No relevant results"}


    def analyze_news(self, stories: list) -> dict:
        results = {}

        whitelist = [

        ]
        blacklist = [
            "Weekly Recap",
            "Threatsday",
            "Weekly Letter v"
        ]
        translation_sources = [
            {"name": "https://www.cert.se/feed/atom.xml", "language": "swedish"}

        ]

        for story in stories:
            story_id = story.get("id")
            for news_item in story.get("news_items", []):
                news_item_id = news_item.get("id")
                news_item_source = news_item.get("source", "")

                # Read existing attributes 
                response = self.core_api.get_news_item_attributes(news_item_id)
                if not response:
                    logger.info(f"Failed to fetch attributes for news item {news_item_id}")
                    continue

                attributes = response.get("attributes", [])
                attributes_dict = {attr["key"]: attr["value"] for attr in attributes}

                # Skip if already checked
                if attributes_dict.get("checked") == "true":
                    logger.info(f"Skipping news item {news_item_id} - already checked")
                    continue

                logger.info(f"news item source: {news_item_source}")
                
                logger.info(f"Analyzing story {story.get('id')} - not yet checked")

                text_content = news_item.get("content", "")
                title_content = news_item.get("title", "")

                combined_content = f"Title: {title_content} Content: {text_content}"

                for ts in translation_sources:
                    if ts["name"] in news_item_source:
                        logger.info(f"Translating news item from {ts['name']} ({ts['language']})")
                        translated_content = self.translate(ts["language"], combined_content)
                        if translated_content == "":
                            logger.error(f"Translation failed for news item {news_item_id} exiting")
                            continue
                        combined_content = translated_content["result"]
                        story_payload = {
                            "id": story_id,
                            "description": combined_content,
                            "attributes": [
                                {"key": "translation", "value": "true"},
                                {"key": "translation_language", "value": ts["language"]},
                            ],
                            "news_items": [
                            {
                            "id": news_item_id,
                            }
                            ]
                        }
                        
                        logger.info(f"Updating story {story_id} with translated content")
                        self.core_api.add_or_update_story(story_payload)
                        time.sleep(10)
                        break  # Only translate once

                if not any(keyword in combined_content for keyword in whitelist):
                    logger.info(f"Skipping news item that does not contain keyword from whitelist.")
                    #  Mark as checked 
                    if self.core_api.update_news_item_attributes( news_item_id,[{"key": "checked", "value": "true"}]):
                        logger.info(f"marked news item {news_item_id} as checked:")
                    continue
                if any(keyword in combined_content for keyword in blacklist):
                    logger.info(f"Skipping news item that contains keyword from blacklist.")
                    #Mark as checked 
                    if self.core_api.update_news_item_attributes( news_item_id,[{"key": "checked", "value": "true"}]):
                        logger.info(f"marked news item {news_item_id} as checked:")
                    continue
                    # Create a prompt for the llm
                prompt_text = (
                        f"Is the article relevant to university cybersecurity? "
                        f"if the article is relevant reply 'Yes, slightly relevant' , 'Yes, relevant', or 'Yes, very relevant'."
                        #f" followed by 3 short/concise bullet points explaining why. "
                        f" If the article is not relevant, reply 'No'."
                        #f"Do not add any other text.\n"
                        f"{combined_content} :end Content")

                time.sleep(20)  # Sleep for 15 seconds between requests to avoid rate limiting
                #logger.info(f"sending request to Vertex Prompt: \n {prompt_text}")
                #response = self.bot_api.api_post("/", {"prompt": prompt_text})
                vertex_response = self.send_llm_request(prompt_text, max_retries=4, base_delay=20.0)

                if not vertex_response["result"]:
                    logger.error("All retries failed. Empty result returned.")
                    continue
                else:
                    logger.info(f"Final Vertex result: {vertex_response['result']}")
                #if not response:
                 #   continue
                #if "error" in response:
                  #  logger.error(response["error"])
                 #   continue
                #  Mark as checked 
                logger.info(f"Received raw response from Vertex: {['raw_response']}")
                # Step 3: Parse the new raw text response from the Gemini API
                #logger.info(f"Received response from Vertex: vertex_response{response}")
                response_text = (vertex_response.get("result")or "" ).strip().lower()
                    #response.get("response") 
                    
                
                logger.info(f"Vertex response text: {response_text}")    
                reasons = []
                relevance_level = "Irrelevant"  # Default to Irrelevant
                #if "" in gemini_response_text: 
                 #   continue   
                if self.core_api.update_news_item_attributes( news_item_id,[{"key": "checked", "value": "true"}]):
                    logger.info(f"marked news item {news_item_id} as checked:")
                #Check for "Yes" or "No" and parse accordingly
                #text_lower = gemini_response_text.lower()
                #first_line = gemini_response_text.splitlines()[0].lower() if gemini_response_text else ""
                if "no" in response_text:
                    relevance_level = "Irrelevant" 
                    continue 

                if "yes," in response_text:
                    if "very relevant" in response_text:
                        relevance_level = "Very Relevant"
                        logger.info(f"{response_text} News item marked as Very Relevant.")   
                    elif "slightly relevant" in response_text:
                        relevance_level = "Slightly Relevant"
                        logger.info(f"{response_text} News item marked as Slightly Relevant.")
                    else:
                        relevance_level = "Relevant"
                        logger.info(f"{response_text} News item marked as Relevant.")
                
                
                     #Split the response to get the bullet points
                    #lines = gemini_response_text.splitlines()
                    # Start from the second line to get the bullet points
                    #reasons = [line.strip() for line in lines[1:] if line.strip()]
 
                # Store the result associated with the news_item_id
                logger.info(f"News item {news_item_id} categorized as {relevance_level} for reasons: {reasons}")
                news_item_id = news_item.get("id")
                results[news_item_id] = {
                
                   "category": relevance_level,
                    #"reasons": reasons,
                    "raw_response": response_text,
                    "story_id": story_id,
                }
                
        return results

    
    def send_llm_request(self, prompt: str, max_retries: int = 4, base_delay: float = 20.0) -> dict:

        attempt = 0
        gemini_response_text = ""
        response = {}

        while attempt < max_retries and gemini_response_text == "":
            logger.info(f"[Attempt {attempt + 1}] Sending request to Vertex Prompt:\n{prompt}")
            response = self.bot_api.api_post("/", {"prompt": prompt})

            if not response:
                logger.warning("No response received from Vertex API.")
            elif "error" in response:
                logger.error(f"Error from Vertex API: {response['error']}")
            else:
                logger.info(f"Received response from Vertex: {response}")
                gemini_response_text = (response.get("result") or "").strip().lower()

            if gemini_response_text == "":
                attempt += 1
                if attempt < max_retries:
                    wait_time = base_delay * (2 ** (attempt - 1))  # exponential backoff
                    logger.warning(f"Empty result. Retrying in {wait_time:.1f} seconds...")
                    time.sleep(wait_time)

        return {"result": gemini_response_text, "raw_response": response}

    def translate(self, language: str, text: str, max_retries: int = 4, base_delay: float = 20.0) -> str:
    
        prompt_text = f"Translate the following {language} text to English with no additional text:\n\n{text}"
        attempt = 0
        translated = ""

        while attempt <= max_retries:
            response = self.bot_api.api_post("/translate", {"prompt": prompt_text})

            # If API failed completely
            if not response:
                logger.warning("No response from API.")
            elif "error" in response:
                error_msg = str(response["error"])
                logger.error(f"Translation error: {error_msg}")

                # Retry only on 429 or 503
                if "429" in error_msg or "503" in error_msg:
                    attempt += 1
                    if attempt <= max_retries:
                        wait_time = base_delay * (2 ** (attempt - 1))
                        logger.warning(f"Retrying in {wait_time:.1f} seconds due to {error_msg}...")
                        time.sleep(wait_time)
                        continue
            else:
                translated = response.get("result") or ""
                break

            attempt += 1

        logger.info(f"Translated text: {translated}")
        return {"result": translated}
    
    def publish_news(self, relevance_results: dict):
        stories_list = []
        for news_item_id, rev_data in relevance_results.items():
            #Check if the news item is "Relevant" before updatin
            category = rev_data.get("category", [])
            reasons = rev_data.get("reasons", [])
            logger.info(f" news id: {news_item_id} catagory: {category}")

            # Skip irrelevant stories
            if category == "Irrelevant":
                logger.info(f"Dropping irrelevant story {news_item_id}")
                continue

            # Build attributes for relevant stories
            attributes = {"key": "relevance_level", "value": category}
            

            # Add reasons as separate attributes (reason_1, reason_2, etc.)
            #for i, reason in enumerate(reasons, start=1):
             #   attributes.append({"key": f"reason_{i}", "value": reason})

            # Update attributes in Core API
            success = self.core_api.update_news_item_attributes(news_item_id, [attributes,],)

            if success:
                logger.info(
                    f"Updated news item {news_item_id} "
                    f"with relevance '{category}' and {len(reasons)} reasons."
                )
            else:
                logger.error(f"Failed to update relevant news item {news_item_id} with attributes.")
       
            #stories_list.append(str(news_item_id)) 
            story_id = rev_data.get("story_id")
            if story_id and str(story_id).lower() != "none":
                stories_list.append(str(story_id)) 
           
        report_payload = {
            "completed": True,
            #"created": "",#datetime.now(timezone.utc).isoformat(),
            "id": str(uuid.uuid4()),  # or uuid
            #"last_updated": "", #datetime.now(timezone.utc).isoformat(),
            "report_item_type_id": 5,
            "title": "Auto Bot Report",
            "attributes": [],
            "stories": stories_list,   # 👈 just put it here
            }
        
        self.core_api.authenticate(username= Config.BOT_USERNAME , password= Config.BOT_PASSWORD)
        response = self.core_api.create_report(report_payload)
        logger.info(f"{response}")
        #product = self.core_api.get_product("1a38e5ef-1f0a-4069-a96c-08800765e856")
        #logger.info(f"{product}")
            #get = self.core_api.get_product("a024a444-7614-4e1e-8062-0cf4258d85dc")
            #logger.info(f"Get product response: {get}")
        response_id = str(response.get("id", None))

        product_payload = {
                "id": str(uuid.uuid4()),
                "report_items": [response_id],
                "title": "Daily Auto Bot Report",
                #"type": "text_presenter",
                "product_type_id": 2

        }
        product_response = self.core_api.create_product(product_payload)
        logger.info(f"Product create response: {product_response}")

        time.sleep(20)
        published = self.core_api.publish_product(product_response.get("id", None),Config.Publisher_ID)
        logger.info(f"Product publish response: {published}")       
       
        #for story in stories:
         #   for news_item in story.get("news_items", []):
          #      if news_item.get('checked', False):
           #         logger.info(f"Skipping story {news_item.get('id')} - already checked")
            #    continue

            #news_item_id = news_item.get("id")
            #if self.core_api.update_news_item_attributes(news_item_id,[{"name": "checked", "value": True}]):
            #    logger.info(f"Successfully updated relevant news item {news_item_id} with attributes.")
            #else:
            #    logger.error(f"Failed to update relevant news item {news_item_id} with attributes.")  
            # If we reach this point, the story.checked was False.
            #logger.info(f"Analyzing story {story.get('id')} - not yet checked")
            #self.update_story_checked_status(story.get('id'), True)
            #story["checked"] = True
            #self.add_or_update_story(story)
            # 

            # 
