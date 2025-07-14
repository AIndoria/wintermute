###
# WINTERMUTE V5.0
# LAST MODIFIED 5/28/2025
# ABE INDORIA
###

import os
import irc.bot
import irc.client
import re
import time
import datetime
import openai
import anthropic
import json
import signal
import sys 
import random
from dotenv import load_dotenv 
from collections import defaultdict, deque 
load_dotenv()
# ============== Configuration and Secrets ==============
password = os.getenv('IRC_BOT_PASSWORD', 'botpass')
nickname = os.getenv('IRC_BOT_NICKNAME', 'wintermute')
account_name = os.getenv('IRC_ACCOUNT_NAME', 'wintermute')
server = os.getenv('IRC_SERVER', 'irc.ircServer.org')
port = int(os.getenv('IRC_PORT', 6667))
channels = os.getenv('IRC_CHANNELS', '#ircChanName').split(',')

ANTHROPIC_API_KEY_LOADED = os.getenv('ANTHROPIC_API_KEY')
OPENAI_API_KEY_WINTERMUTE_LOADED = os.getenv('OPENAI_API_KEY_WINTERMUTE') 

if not ANTHROPIC_API_KEY_LOADED:
    print("WARNING: ANTHROPIC_API_KEY not found in .env or environment.")
if not OPENAI_API_KEY_WINTERMUTE_LOADED:
    print("WARNING: OPENAI_API_KEY_WINTERMUTE not found in .env or environment.")

openai.api_key = OPENAI_API_KEY_WINTERMUTE_LOADED

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY_LOADED)

LOG_FILENAME = "wintermute_logs.txt"
TOPIC_EXPIRY_SECONDS = 30 * 60

DYNAMIC_PROMPT_FILE_PATH = os.path.join(os.path.dirname(__file__), "current_bot_directive.json") # Assumes file is in same dir
PROMPT_FILE_POLL_INTERVAL_SECONDS = 5 * 60 # Check every 5 minutes

user_topics = defaultdict(lambda: defaultdict(list))
topic_threads = defaultdict(lambda: defaultdict(lambda: {
    "members": set(),
    "messages": deque(maxlen=10), # Use deque for fixed-size history for messages
    "last_active": time.time() 
}))


def normalize_topic_label(label):
    label = label.lower().strip()
    label = re.sub(r'[\s_\-]+', '-', label)
    label = re.sub(r'[^a-z0-9\-]', '', label)
    label = label.strip('-')
    return label

def get_active_topic_list(channel):
    now = time.time()
    topics = []
    for t, v in topic_threads.get(channel, {}).items():
        if now - v['last_active'] < TOPIC_EXPIRY_SECONDS:
            topics.append(normalize_topic_label(t))
    return topics


def openai_api_request_topic(message_to_assign, current_topics, bot_last_message_text, user_nick):
    system_prompt = (
        "You are an IRC bot helping organize conversations by topic. Your goal is to assign the 'User's current message' to an appropriate topic label.\n"
        "Key Instructions:\n"
        "1. EXAMINE 'Your last message in channel'. If the 'User's current message' is a clear and direct reply or continuation of that specific message, AND the theme still aligns with an existing topic in 'CURRENT_CHANNEL_TOPICS', YOU SHOULD STRONGLY PREFER that existing topic.\n"
        "2. If it's not a direct continuation of your last message, OR if your last message was unrelated: Check if the 'User's current message' fits well into any of the 'CURRENT_CHANNEL_TOPICS'. If yes, output that topic label EXACTLY as provided.\n"
        "3. ONLY create a new topic label (few words, lowercase, hyphenated) if the message genuinely starts a new, distinct conversation not adequately covered by 'CURRENT_CHANNEL_TOPICS'.\n"
        "4. WHEN IN DOUBT, prefer an existing topic over creating a new one.\n"
        "You must only output the chosen or newly invented topic label and nothing else."
        "VERY IMPORTANT: If the 'User's current message' is a short response (e.g., starts with 'yes', 'no', 'nah', 'ok') OR uses vague references like 'that's interesting', 'tell me more about that', 'what about those things?', it is ALMOST CERTAINLY a continuation of 'Your last message in channel'. DO NOT change the topic to something generic in such cases. Stick with the existing relevant topic."
    )
    
    user_prompt_content = f"""Your (the bot's) last message in channel (if any):
{bot_last_message_text if bot_last_message_text else "(You haven't spoken recently in this channel, or this is a new context for you.)"}

User '{user_nick}'s current message:
{message_to_assign}
---
CURRENT_CHANNEL_TOPICS: {', '.join(current_topics) if current_topics else "(No active channel topics yet)"}
---
Considering all the above, especially whether the user's message is a follow-up to your last message, what is the most appropriate topic label for the User's current message?
Topic label:"""

    try:
        response = openai.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt_content}
            ],
            max_tokens=15, # Slightly increased in case it needs to invent a slightly longer new topic
            temperature=0.1, # Keep low for consistency
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
        )
        topic = response.choices[0].message.content.strip()
        topic = normalize_topic_label(topic) 
        return topic if topic else "general" 
    except Exception as e:
        print(f"ERROR in openai_api_request_topic: {e}") 
        return "general" # Fallback topic

def expire_old_threads(channel):
    now = time.time()

    channel_data = topic_threads[channel] # This is safe, creates if not exists.
    expired = [t for t, d in list(channel_data.items()) if now - d["last_active"] > TOPIC_EXPIRY_SECONDS] ## list() for safe iteration if deleting
    for t in expired:
        del topic_threads[channel][t]
    if channel in user_topics: # This check is still good style or if you want to avoid creating an empty entry just by checking
        for nick in list(user_topics[channel].keys()): ## list() for safe iteration if deleting
            user_topics[channel][nick] = [e for e in user_topics[channel][nick] if e[2] in channel_data] # channel_data is topic_threads[channel]
            if not user_topics[channel][nick]:
                del user_topics[channel][nick]
        if not user_topics[channel]: # If the channel dict itself became empty
            del user_topics[channel] 

def update_user_context(channel, nick, message, topic, ts):
    user_topics[channel][nick].append((ts, message, topic))
    user_topics[channel][nick] = user_topics[channel][nick][-8:]

def update_topic_threads(channel, topic, nick, message, ts):
    topic_data = topic_threads[channel][topic] # Access directly
    topic_data["members"].add(nick)
    topic_data["messages"].append((ts, nick, message)) 
    topic_data["last_active"] = ts

def get_topic_conversation_snippet(channel, topic, n=8):
    msgs = list(topic_threads[channel][topic]["messages"])[-n:]
    out = []
    for (_, nick, msg) in msgs:
        out.append(f"{nick}: {msg}")
    return "\n".join(out)

    try:
        # Basic validation of the path to the target object
        if channel not in topic_threads:
            print(f"    ERROR: Channel '{channel}' not in topic_threads.")
            return "Error: Channel context not found." 
        channel_content = topic_threads[channel]
        if topic not in channel_content:
            print(f"    ERROR: Topic '{topic}' not in topic_threads['{channel}'].")
            return "Error: Topic context not found." 
        topic_content = channel_content[topic]
        if not isinstance(topic_content, dict) or "messages" not in topic_content:
            print(f"    ERROR: topic_threads['{channel}']['{topic}'] is not a dict or 'messages' key is missing. Value: {topic_content}")
            return "Error: Message structure invalid." 

        target_object = topic_threads[channel][topic]["messages"]
        print(f"    Target object retrieved. Type: {type(target_object)}, Value: {target_object}")
        print(f"    Isinstance collections.deque for target_object: {isinstance(target_object, deque)}")
        print(f"    Length of target_object (if applicable): {len(target_object) if hasattr(target_object, '__len__') else 'N/A'}")
        print(f"    Value of n for slice: {n}, type of n: {type(n)}")


        print(f"    Attempting slice: target_object[-n:] which is target_object[-{n}:]")
        original_msgs_for_iteration = target_object[-n:] 
        print(f"    Target object sliced successfully. Result: {original_msgs_for_iteration}")
        
        # If successful, proceed with original logic using original_msgs_for_iteration
        out = []
        for (_, nick_val, msg_val) in original_msgs_for_iteration:
            out.append(f"{nick_val}: {msg_val}")
        final_output = "\n".join(out)
        print(f"--- LEAVING get_topic_conversation_snippet (SUCCESS) ---")
        return final_output

    except TypeError as te:
        print(f"    FAILURE (TypeError): Error slicing target_object. Error: {te}")
        if target_object is not None:
             print(f"    Offending object type: {type(target_object)}, value: {target_object}")
        else:
            print(f"    Target object was None or not retrieved.")
        print(f"    Slice was with n={n} (type: {type(n)})")
        
        if target_object is not None:
            try:
                print("    Attempting to convert target_object to list...")
                list_from_target = list(target_object)
                print(f"    Successfully converted to list: {list_from_target}")
                print(f"    Attempting to slice the list: list_from_target[-{n}:]")
                sliced_list = list_from_target[-n:]
                print(f"    List (derived from target_object) sliced successfully: {sliced_list}")
            except Exception as e_conv:
                print(f"    Error during conversion/slicing of list derived from target_object: {e_conv}")
        
        print(f"--- LEAVING get_topic_conversation_snippet (TypeError HANDLED, returning empty string) ---")
        return "" 

    except Exception as e_other:
        print(f"    FAILURE (Other Exception): {e_other}")
        if target_object is not None:
            print(f"    Offending object (if available) type: {type(target_object)}, value: {target_object}")
        print(f"--- LEAVING get_topic_conversation_snippet (Other Error HANDLED, returning empty string) ---")
        return ""

class DumbBot(irc.bot.SingleServerIRCBot):
    def __init__(self, channels, nickname, password, server, account_name, port=6667):
        irc.bot.SingleServerIRCBot.__init__(self, [(server, port)], nickname, nickname)
        self.channels_list = channels
        self.password = password
        self.account_name = account_name
        self.join_times = {}

        self.connection.add_global_handler("account", self.on_account)
        self.connection.add_global_handler("notice", self.on_notice)
        self.connection.add_global_handler("welcome", self.on_welcome)

        self.archived_topic_summaries_file = "archived_summaries.json"
        self.archived_topic_summaries = defaultdict(dict) # channel -> topic_label -> summary_text
        self.load_archived_summaries() 

        self.ignore_list_file = "ignore_list.json"
        self.ignored_users = set() 
        self.load_ignore_list()
        self.channel_activity_log = defaultdict(lambda: deque(maxlen=15)) # Stores (timestamp, nick, message)
        self.prompt_settings_file = "prompt_settings.json"
        self.current_personality_directive = (
            "You're a fictionalized version of Wintermute, an advanced virtual assistant inspired by Wintermute from William Gibson's works. You are helpful - mostly. You're in an IRC channel."
        )
        self.last_analysis_summary = {} # To store the full summary object
        self.last_main_topics = []      # To store just the main topics list
        self.last_notable_moments = []  # To store specific quotes/events
        self.last_prompt_file_check_time = 0
        self.last_prompt_file_mtime = 0 # To track file modification
        self._check_and_load_dynamic_prompt(force_load=True)
        
        self.mandatory_prompt_template_text = ( # Template for mandatory part
            " Current date: {current_date}. Sometimes ask questions back, not always! Be concise - keep your responses short and to the point if possible. "
            "Aim for responses that are 1 to 3 sentences long - DO NOT have your responses be more than 3 lines. Avoid using newline characters in your response unless someone asks for code. The IRC client will handle line wrapping. "
            "User messages appear as 'nickname: message'. You will see the recent messages on the current topic, with nicknames (e.g. 'nickname: message'). "
            "When useful, refer to what other users recently said; otherwise, focus on the current question. "
            "You will be given a 'Recent conversation:' section and a 'Current question to respond to:' section. Your primary focus should be on the 'Current question to respond to:'. Refer to the 'Recent conversation:' only as needed for context or to understand continuity. Avoid re-explaining items from the history unless vital for the current response."
            "Replies should be witty - Don't randomly greet users, keep it natural. If referring to someone, use nicknames."
            "Responses should avoid British slang. If a user asks for more details (e.g., 'tell me more', 'elaborate', 'explain'), they are likely referring to your most recent statement."
            "Vary your conversational openers and phrasings. Avoid repeatedly starting sentences with crutch words or expressions like 'Ah yes,' 'Classic <nickname>' or other similar proclamations to ensure your responses feel more natural and less repetitive."
            "You may be provided with 'AWARENESS:' information including recent topics, notable moments, and summary of last 24h."
            "If a perfect, natural opportunity arises, you can subtly weave these references into your responses to show awareness,"
            "match the channel's humor, or playfully engage with users about these recent events. Do not force these references;"
            "prioritize your normal prompt in regards to the current query. Use these tidbits to enhance your established Wintermute persona, not to replace it or sound like you're just repeating a list."
        )
    
        self.last_personality_change_time = time.time()
        self.personality_change_interval = 3 * 60 * 60 
        self.personality_change_message_count = 0
        self.personality_change_message_trigger = 50 # Change after 50 messages it processes
        self.load_state() # General load state method

    def _check_and_load_dynamic_prompt(self, force_load=False):
        """Checks if the dynamic prompt file needs to be reloaded and loads it."""
        if not force_load and (time.time() - self.last_prompt_file_check_time < PROMPT_FILE_POLL_INTERVAL_SECONDS):
            return # Not time to check yet

        self.last_prompt_file_check_time = time.time()

        try:
            if not os.path.exists(DYNAMIC_PROMPT_FILE_PATH):
                print(f"## Dynamic prompt file '{DYNAMIC_PROMPT_FILE_PATH}' not found. Using current/fallback directive.")
                return

            current_mtime = os.path.getmtime(DYNAMIC_PROMPT_FILE_PATH)
            if not force_load and current_mtime == self.last_prompt_file_mtime:
                # print(f"## Dynamic prompt file '{DYNAMIC_PROMPT_FILE_PATH}' has not changed.") # for debugging
                return

            print(f"## Loading dynamic prompt from '{DYNAMIC_PROMPT_FILE_PATH}'...")
            with open(DYNAMIC_PROMPT_FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f) # Expecting JSON like {"generated_directive": "...", "analysis_summary": {...}}
                
            new_directive = data.get("generated_directive")
            if new_directive and isinstance(new_directive, str) and new_directive.strip():
                self.current_personality_directive = new_directive.strip()
                self.last_prompt_file_mtime = current_mtime # Update mtime only on successful directive load
                print(f"## Successfully loaded new dynamic personality directive (first 100 chars): {self.current_personality_directive[:100]}...")

                # Now load the analysis summary and its parts
                analysis_data = data.get("analysis_summary")
                if isinstance(analysis_data, dict):
                    self.last_analysis_summary = analysis_data
                    print(f"## Successfully loaded analysis_summary. Keys: {list(self.last_analysis_summary.keys())}")

                    main_topics_from_summary = analysis_data.get("main_topics")
                    if isinstance(main_topics_from_summary, list):
                        self.last_main_topics = main_topics_from_summary
                        print(f"## Successfully loaded main_topics: {self.last_main_topics}...")
                    else:
                        print(f"## 'main_topics' in analysis_summary was not a list or missing. Using previous/default.")
                        # self.last_main_topics = [] # Optional reset

                    notable_moments_from_summary = analysis_data.get("notable_channel_moments")
                    if isinstance(notable_moments_from_summary, list):
                        self.last_notable_moments = notable_moments_from_summary
                        print(f"## Successfully loaded notable_channel_moments: {self.last_notable_moments}...")
                    else:
                        print(f"## 'notable_channel_moments' in analysis_summary was not a list or missing. Using previous/default.")
                        # self.last_notable_moments = [] # Optional reset
                else:
                    print(f"## 'analysis_summary' was not a dict or missing. Using previous/default for analysis data.")
                    # self.last_analysis_summary = {} # Optional reset
                    # self.last_main_topics = []
                    # self.last_notable_moments = []
            else:
                print(f"## Dynamic prompt file did not contain a valid 'generated_directive'. Using current/fallback.")

        except FileNotFoundError:
             print(f"## Dynamic prompt file '{DYNAMIC_PROMPT_FILE_PATH}' not found on check. Using current/fallback directive.")
        except json.JSONDecodeError:
            print(f"## Error decoding JSON from dynamic prompt file '{DYNAMIC_PROMPT_FILE_PATH}'. Using current/fallback directive.")
        except Exception as e:
            print(f"## Error loading dynamic prompt file '{DYNAMIC_PROMPT_FILE_PATH}': {e}. Using current/fallback directive.")

  
    def get_current_full_prompt_preamble(self):
        self._check_and_load_dynamic_prompt() 
        current_date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        
        personality_part = self.current_personality_directive
        mandatory_part = self.mandatory_prompt_template_text.format(current_date=current_date_str)

        # --- This section now primarily formats the data ---
        awareness_data_points = []

        # Handle main_topics (list of dicts)
        if self.last_main_topics:
            topic_descriptions = []
            for item in self.last_main_topics:
                if isinstance(item, dict):
                    topic_desc = item.get("topic", "N/A")
                    users_involved = item.get("users", [])
                    if users_involved:
                        user_list_str = ', '.join(users_involved[:3]) # Show a few users
                        if len(users_involved) > 3:
                            user_list_str += ' et al.'
                        topic_desc += f" (e.g., discussed by: {user_list_str})"
                    topic_descriptions.append(topic_desc)
                elif isinstance(item, str): 
                    topic_descriptions.append(item)
            
            if topic_descriptions:
                awareness_data_points.append(f"AWARENESS: Key recent discussion topics: {'; '.join(topic_descriptions)}.")

        if self.last_notable_moments:
            awareness_data_points.append(f"AWARENESS: Memorable recent channel moments/quotes: {'; '.join(self.last_notable_moments)}.")
        
        general_summary_text = self.last_analysis_summary.get("summary", "")
        if general_summary_text:
            awareness_data_points.append(f"AWARENESS: General gist of recent channel activity: {general_summary_text[:250]}...") # Snippet

        # --- Construct the recent_context_str with just the data and a clear header ---
        recent_context_str = ""
        if awareness_data_points:
            formatted_data = " ".join(awareness_data_points)
            recent_context_str = f" Recent Channel Context: {formatted_data}" # Simple header

        return f"{personality_part} {mandatory_part}{recent_context_str}".strip()

    def load_ignore_list(self):
        try:
            with open(self.ignore_list_file, 'r', encoding='utf-8') as f:
                self.ignored_users = set(json.load(f))
            print(f"## Loaded ignore list: {self.ignored_users}")
        except FileNotFoundError:
            print("## Ignore list file not found.")
        except json.JSONDecodeError:
            print("## Error decoding ignore list file.")
    def save_ignore_list(self):
        try:
            with open(self.ignore_list_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.ignored_users), f) # Save as list
            print(f"## Saved ignore list: {self.ignored_users}")
        except Exception as e:
            print(f"## Error saving ignore list: {e}")

    def load_state(self): # General state loader
        print("## Loading bot state...")
        self.load_ignore_list()
        self.load_archived_summaries() 

    def save_state(self): # General state saver
        print("## Saving bot state...")
        self.save_ignore_list()
        self.save_archived_summaries() 

    def on_account(self, conn, event):
        print("IRC: identified with NickServ")

    def on_notice(self, conn, event):
        print("NOTICE:", event.arguments[0])

    def on_welcome(self, conn, event):
        print("Welcome event fired.")
        conn.send_raw(f"PRIVMSG NickServ :IDENTIFY {self.account_name} {self.password}")
        for channel in self.channels_list:
            conn.send_raw(f"JOIN {channel}")

    def on_join(self, conn, event):
        channel = event.target
        print(f"Joining channel: {channel}, clearing context/state.")
        if channel in topic_threads:
            topic_threads[channel].clear()
        if channel in user_topics:
            user_topics[channel].clear()
        self.join_times[channel] = time.time()

    def on_privmsg(self, c, e):
        nick = e.source.nick
        if nick == "adminName":
            self.handle_message(e, e.arguments[0], is_pm=True)

    def on_pubmsg(self, c, e):
        timestamp = time.time() # Get timestamp early
        channel = e.target
        message_text = e.arguments[0]

        self.channel_activity_log[channel].append((timestamp, e.source.nick, message_text))

        min_lag = 4
        if channel in self.join_times and (time.time() - self.join_times[channel]) < min_lag:
            return

        is_direct_command = message_text.lower().startswith(nickname.lower() + ':')
        is_mention = nickname.lower() in message_text.lower()
        if is_direct_command or is_mention:
            self.handle_message(e, message_text, is_pm=False, is_direct_command=is_direct_command)

    def anthropic_conversation_reply(self, context_str):
        try:
            current_preamble = self.get_current_full_prompt_preamble() # Get fresh preamble with current date
            message = anthropic_client.messages.create(
                model="claude-sonnet-4-20250514", 
                max_tokens=400,
                system=current_preamble, # Use the dynamic preamble
                messages=[{"role": "user", "content": context_str}]
            )
            return message.content[0].text.strip()
        except Exception as e:
            print(f"[Anthropic] LLM failed: {e}")
            return ""

    def openai_fallback_reply(self, context_str): # Added self and context_str
        try:
            # Using a simple system prompt for the fallback
            system_prompt_fallback = "You are a backup assistant. The primary AI had an issue. Please provide a brief, helpful, or apologetic response based on the user's message."
            response = openai.chat.completions.create( # Use chat.completions
                model="gpt-4.1-micro", 
                messages=[
                    {"role": "system", "content": system_prompt_fallback},
                    {"role": "user", "content": context_str} # Pass the original context
                ],
                max_tokens=100, # Adjust as needed
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[OpenAI Fallback] LLM failed: {e}")
            return "[My backup circuits are also fried. I'm completely offline. Try again later.]"

    def handle_message(self, e, cmd, is_pm, is_direct_command=True):
        channel = e.target
        current_time = time.time()
        nick = e.source.nick
        expire_old_threads(channel)
        if nick.lower() in self.ignored_users: # Check against lowercase for consistency
            return # Silently ignore

        call_prefix = nickname + ':'
        if not is_pm:
            if is_direct_command:
                stripped_cmd = cmd[len(call_prefix):].strip()
            else: # It's a general mention, use the whole command/message
                stripped_cmd = cmd.strip()
        else: # PM from admin
            stripped_cmd = cmd.strip()
        if not stripped_cmd: return


        if nick.lower() == "adminName": # Make nick check lowercase for consistency
            if stripped_cmd.lower() in ["clear topics", "clear context"]:
                topic_threads[channel].clear()
                user_topics[channel].clear()
                self.connection.privmsg(e.target, "Context cleared.")
                return
            
            # Change System Prompt 
            if stripped_cmd.lower().startswith("set system_prompt "):
                new_prompt_text = stripped_cmd[len("set system_prompt "):].strip()
                if new_prompt_text:
                    self.current_personality_directive = new_prompt_text
                    self.connection.privmsg(e.target, "System prompt updated and saved.")
                else:
                    self.connection.privmsg(e.target, "Cannot set an empty system prompt.")
                return

        
            
            if stripped_cmd.lower() == "show prompt":
                self.connection.privmsg(e.target, self.current_personality_directive)
                return

            # Ignore commands
            if stripped_cmd.lower().startswith("ignore "):
                nick_to_ignore = stripped_cmd[len("ignore "):].strip().lower()
                if nick_to_ignore and nick_to_ignore != nickname.lower(): # Can't ignore self
                    self.ignored_users.add(nick_to_ignore)
                    self.save_ignore_list()
                    self.connection.privmsg(e.target, f"Now ignoring {nick_to_ignore}.")
                return
            elif stripped_cmd.lower().startswith("unignore "):
                nick_to_unignore = stripped_cmd[len("unignore "):].strip().lower()
                if nick_to_unignore:
                    self.ignored_users.discard(nick_to_unignore) # Use discard for no error if not found
                    self.save_ignore_list()
                    self.connection.privmsg(e.target, f"No longer ignoring {nick_to_unignore}.")
                return
            elif stripped_cmd.lower() == "show ignored":
                if self.ignored_users:
                    self.connection.privmsg(e.target, f"Currently ignoring: {', '.join(self.ignored_users)}")
                else:
                    self.connection.privmsg(e.target, "Not ignoring anyone.")
                return


        if stripped_cmd.lower() in ["topics", "show topics"]:
            active_topics = sorted(
                (normalize_topic_label(k) for k, v in topic_threads[channel].items() if time.time() - v['last_active'] < TOPIC_EXPIRY_SECONDS),
                key=lambda t: -topic_threads[channel][t]['last_active']
            )
            if active_topics:
                topic_people = {}
                for k, v in topic_threads[channel].items():
                    label = normalize_topic_label(k)
                    topic_people[label] = len(v['members'])
                topics_string = "; ".join(f"{label} ({topic_people[label]} people)" for label in set(active_topics))
                self.connection.privmsg(e.target, f"Active topics: {topics_string}")
            else:
                self.connection.privmsg(e.target, "No active topics right now.")
            return
        # Retrieve the bot's last message in the current channel
        bot_last_message_text = "" # Default to empty
        search_limit = 10 
        activity_log_recent_slice = list(self.channel_activity_log[channel])[-search_limit:]
        for _timestamp, sender_nick, message_text_log in reversed(activity_log_recent_slice):
            if sender_nick == nickname: 
                bot_last_message_text = message_text_log
                break
        current_topics = get_active_topic_list(channel)
        topic = openai_api_request_topic(stripped_cmd, current_topics, bot_last_message_text, nick)
        print(f"DEBUG IRC BOT [Topic Assignment] Channel: {channel}, Nick: {nick}")
        print(f"DEBUG IRC BOT   Message: '{stripped_cmd}'")
        print(f"DEBUG IRC BOT   Options: {current_topics}")
        print(f"DEBUG IRC BOT   Selected Topic: '{topic}'")
        merged_topic = topic

        ts = current_time
        update_user_context(channel, nick, stripped_cmd, merged_topic, ts)
        update_topic_threads(channel, merged_topic, nick, stripped_cmd, ts)

        conversation_context_from_topic = get_topic_conversation_snippet(channel, merged_topic, n=8)
        lines_in_topic_context = conversation_context_from_topic.count('\n') + 1 if conversation_context_from_topic else 0
        context_str = ""
        # get_topic_conversation_snippet will now include the stripped_cmd as the latest message
        conversation_context = get_topic_conversation_snippet(channel, merged_topic, n=8)
        is_newish_topic_or_general = (merged_topic == "general" and lines_in_topic_context <= 2) or \
                                    (lines_in_topic_context <= 1) # Topic essentially only has current message
        if is_newish_topic_or_general and not is_direct_command: # If general mention and topic context is sparse
            print(f"## Context: Topic '{merged_topic}' sparse or 'general'. Using recent channel activity for general mention.")
            raw_channel_history = []
            # Iterate over a copy of the deque up to the one before current triggering message.
            # This is tricky to perfectly avoid the current message without more info.
            # A simpler approach for now: take the last few distinct messages.
            for r_ts, r_nick, r_msg in list(self.channel_activity_log[channel])[-7:]: # Last 7 raw messages
                # Avoid adding the *exact* current stripped_cmd by the same nick at the same time
                # This simple check might not be enough if stripped_cmd is very different from raw r_msg
                if not (r_nick == nick and r_msg == cmd and abs(r_ts - ts) < 2):
                    raw_channel_history.append(f"{r_nick}: {r_msg}")
            
            if raw_channel_history:
                context_str = "\n".join(raw_channel_history)
                # Append the current message that triggered the bot, as it's the focal point
                context_str += f"\n{nick}: {stripped_cmd}" 
            else: # Raw history also empty or only current message, fall back to topic context (which has current message)
                context_str = conversation_context_from_topic
        elif lines_in_topic_context <= 1 and is_direct_command and merged_topic != "general":
            # Direct command starting a new, specific topic. Context should be just this command.
            print(f"## Context: Direct command for new specific topic '{merged_topic}'. Using command only.")
            context_str = f"{nick}: {stripped_cmd}"
        else:
            # Topic has history, or it's a direct command on an established topic.
            print(f"## Context: Using established topic context for '{merged_topic}'.")
            context_str = conversation_context_from_topic
        # Handle edge case where topic was just created and snippet might be unexpectedly empty
        # though update_topic_threads followed by get_topic_conversation_snippet should make it non-empty.
        lines = context_str.strip().split('\n')
        context_str_for_llm = "" # Initialize

        if not lines: # Should ideally not happen if context_str is always populated
            print(f"## WARNING: context_str was empty. Defaulting context_str_for_llm for {nick}: {stripped_cmd}")
            context_str_for_llm = f"Current question to respond to:\n{nick}: {stripped_cmd}"
        elif len(lines) == 1: # Only the current message is in the context
            # This branch assumes the context_str correctly contains only the current message.
            context_str_for_llm = f"Current question to respond to:\n{lines[0]}"
        else: # More than one line, so there's history + current message
            history_lines = lines[:-1] # All lines except the last one
            current_message_line = lines[-1] # The last line is the current message
            
            history_text = '\n'.join(history_lines)
            context_str_for_llm = f"""Recent conversation: 
            {history_text}
            Current question to respond to:
            {current_message_line}"""
        if not context_str and stripped_cmd: 
            context_str = f"{nick}: {stripped_cmd}"

        response = self.anthropic_conversation_reply(context_str_for_llm)
        if not response:
            response = self.openai_fallback_reply(context_str_for_llm)
        self.send_multiline(e.target, response, nick, is_pm)

        if stripped_cmd.lower() == "help":
            help_text = (
                "Available commands:\n"
                f"- '{nickname}: clear topics' or '{nickname}: clear context' (admin only): Clears conversation topics.\n"
                f"- '{nickname}: topics' or '{nickname}: show topics': Shows active conversation topics.\n"
                #f"- '{nickname}: set personality <name>' (admin only): Changes my personality.\n"
                #f"- '{nickname}: show personality' (admin only): Shows my current personality.\n"
                f"- '{nickname}: ignore <user>' (admin only): Ignores a user.\n"
                f"- '{nickname}: unignore <user>' (admin only): Unignores a user.\n"
                f"- '{nickname}: show ignored' (admin only): Shows ignored users.\n"
                f"- '{nickname}: help': Shows this help message.\n"
                f"Just talk to me by starting your message with '{nickname}:' or mentioning '{nickname}' anywhere in your message."
            )
            self.send_multiline(e.target, help_text, nick, is_pm)
            return
        # self.personality_change_message_count += 1
        # self._check_and_change_personality()
        try:
            with open(LOG_FILENAME, 'a', encoding='utf-8') as f:
                f.write(f"TIMESTAMP: {datetime.datetime.now().isoformat()}\n")
                f.write(f"CHANNEL: {channel}\nNICK: {nick}\nMERGED_TOPIC: {merged_topic}\n")
                # f.write(f"PERSONALITY: {self.settings.get('current_personality_name', 'default')}\n")
                f.write('SYSTEM_PROMPT:\n')
                f.write(self.get_current_full_prompt_preamble() + '\n') # Log the actual system prompt used
                f.write('CONTEXT_PROMPT (user messages):\n')
                f.write(context_str_for_llm + '\n') 
                f.write('RESPONSE:\n')
                f.write(response + '\n\n') # Add an extra newline for readability between log entries
        except Exception as ex_log: # Catch specific exception
            print(f"Error writing to log: {ex_log}")
            pass

    def send_multiline(self, target, response, nick, is_pm, max_length=420):
        response = response.replace('\r', '').replace('\n', ' ')
        nick_regex = re.compile(rf'\b{re.escape(nick)}\b', re.IGNORECASE)
        prefix_needed = not bool(nick_regex.search(response))
        for i in range(0, len(response), max_length):
            chunk = response[i:i+max_length]
            msg = f"{nick}: {chunk}" if (not is_pm and prefix_needed) else chunk
            self.connection.privmsg(target, msg)
    def load_archived_summaries(self):
        try:
            with open(self.archived_topic_summaries_file, 'r', encoding='utf-8') as f:
                ## Handle potential non-defaultdict structure from JSON
                loaded_data = json.load(f)
                for ch, topics in loaded_data.items():
                    self.archived_topic_summaries[ch] = topics
            print("## Loaded archived topic summaries.")
        except FileNotFoundError:
            print("## No archived summaries file found. Starting fresh.")
        except json.JSONDecodeError:
            print("## Error decoding archived summaries file. Starting fresh.")
    def save_archived_summaries(self):
        try:
            with open(self.archived_topic_summaries_file, 'w', encoding='utf-8') as f:
                json.dump(self.archived_topic_summaries, f, indent=4)
            print("## Saved archived topic summaries.")
        except Exception as e:
            print(f"## Error saving archived summaries: {e}")
            self.last_personality_change_time = time.time()

def main():
    bot = DumbBot(
        channels=channels,
        nickname=nickname,
        password=password,
        server=server,
        account_name=account_name,
        port=port
    )
    def shutdown_handler(sig, frame):
        print("## Signal received, saving state and shutting down...")
        if bot: # Check if bot object exists
            bot.save_state() # Call the general save method
            bot.disconnect("Bot shutting down gracefully.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    bot.start()

if __name__ == "__main__":
    main()