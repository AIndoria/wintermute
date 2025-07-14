import openai
import json
import datetime
import os
import re
import subprocess 
import shutil 
from dotenv import load_dotenv 
load_dotenv()
# --- CONFIGURATION ---
OPENAI_API_KEY_LOADED_PROMPT_GEN = os.getenv("OPENAI_API_KEY_PROMPT_GEN")
if not OPENAI_API_KEY_LOADED_PROMPT_GEN:
    raise ValueError("Missing OPENAI_API_KEY_PROMPT_GEN environment variable. Set it in your .env file.")

openai.api_key = OPENAI_API_KEY_LOADED_PROMPT_GEN 
WEECHAT_LOG_FILE_LOCAL_PATH = "./irc.serverName.#channelName.weechatlog"
CHANNEL_NAME_IN_LOG = "#channelName" 
HOURS_LOOKBACK = 24
TOKEN_THRESHOLD_FOR_MINI = 120000 # User-defined token threshold
# Output file for wintermute.py
# Ensure wintermute.py's DYNAMIC_PROMPT_FILE_PATH matches this
OUTPUT_JSON_FILE_PATH = "./current_bot_directive.json"
ARCHIVE_DIR_PATH = os.path.join(os.path.dirname(OUTPUT_JSON_FILE_PATH), "directive_archive")
PREFERRED_ANALYSIS_MODEL = "gpt-4.1-mini"
SMALLER_ANALYSIS_MODEL = "gpt-4.1-nano" # For very large logs if micro is too slow/costly
PROMPT_GEN_MODEL = "gpt-4.1-mini" # Or even nano, as its input is small

# Threshold for choosing smaller model (character count of the day's log text)
# Adjust based on typical log sizes and model context windows/costs
MODEL_CHOICE_CHAR_THRESHOLD = 100000 # Approx 20k tokens
MAX_CHARS_TO_SEND_TO_ANALYSIS_LLM = 1000000 # Cap at 1 million characters (~250k tokens)
# --- STAGE 1: DEEP CHANNEL ANALYSIS ---

def fetch_and_prepare_weechat_logs(log_file_path, hours_lookback=24):
    """
    Reads a WeeChat log file, filters messages from the last `hours_lookback` hours,
    and formats them as "nick: message".
    """
    print(f"Processing WeeChat log: {log_file_path} for last {hours_lookback} hours.")
    relevant_log_entries = []
    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"ERROR: Log file not found: {log_file_path}")
        return None
    except Exception as e:
        print(f"ERROR: Could not read log file {log_file_path}: {e}")
        return None

    cutoff_datetime = datetime.datetime.now() - datetime.timedelta(hours=hours_lookback)
    
    # WeeChat log format: YYYY-MM-DD HH:MM:SS<TAB><PREFIX_NICK><TAB><MESSAGE>
    # Example line: 2025-03-27 01:02:17	@test	test2: Do you read
    # Example join/part: 2025-05-21 00:09:22	-->	test (test@test-tf7.tf0.3tvs21.IP) has joined #channelName
    # We want to skip join/part/quit/nick changes etc. for content analysis for now.
    
    # Regex to capture main parts and identify user messages vs system/join-part messages
    # This regex tries to capture the nick more cleanly from prefix_nick field
    # It assumes nick does not contain tabs. Message can contain anything.
    # Line starts with date, time, tab, then either "-->", "<--", "---" (system) or a nick field, then tab, then message.
    log_pattern = re.compile(
        r"^(?P<timestamp_str>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\t"
        r"(?P<sender_field>[^\t]+)\t"
        r"(?P<message>.+)$"
    )
    # Nick prefixes to strip from sender_field if it's a user message
    nick_prefixes_to_strip = re.compile(r"^[~&@%+\s]+") # Common prefixes and leading spaces

    for line_num, line_content in enumerate(reversed(lines)): # Process recent lines first
        line_content = line_content.strip()
        match = log_pattern.match(line_content)
        if not match:
            # print(f"Line {len(lines)-line_num} did not match pattern: {line_content[:100]}")
            continue

        parts = match.groupdict()
        try:
            msg_datetime = datetime.datetime.strptime(parts["timestamp_str"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            # print(f"Could not parse timestamp on line {len(lines)-line_num}: {parts['timestamp_str']}")
            continue

        if msg_datetime < cutoff_datetime:
            # print(f"Reached cutoff time at line {len(lines)-line_num}. Processed {len(relevant_log_entries)} entries.")
            break # Since we are reading in reverse, we can stop

        sender_field = parts["sender_field"].strip()
        message = parts["message"].strip()

        # Filter out common server messages / non-user chat
        if sender_field in ["-->", "<--", "---"] or "irc.serverName.org" in sender_field: # Adjust if your server name is different
            continue
        if message.startswith("has joined") or message.startswith("has quit") or \
           message.startswith("has parted") or message.startswith("is now known as") or \
           message.startswith("Mode ") or message.startswith("***"):
            continue
            
        # Clean up nick
        nick = nick_prefixes_to_strip.sub("", sender_field)

        if not nick or not message: # Skip if nick or message is empty after processing
            continue
            
        if nick.lower() == "cloudBot":
            continue # Skip all messages from cloudBot or similar bots

        relevant_log_entries.append(f"{nick}: {message}")

    if not relevant_log_entries:
        print("No relevant user messages found in the lookback period.")
        return None
        
    # Entries are in reverse chronological order, so reverse again for chronological
    concatenated_logs = "\n".join(reversed(relevant_log_entries))
    print(f"Prepared {len(relevant_log_entries)} log entries for analysis ({len(concatenated_logs)} chars).")
    return concatenated_logs


def select_analysis_model(full_log_text_char_count):
    """
    Selects an analysis model based on the approximate token count of the input.
    Uses PREFERRED_ANALYSIS_MODEL unless token count exceeds TOKEN_THRESHOLD_SWITCH_TO_ECONOMY.
    """
    # Using a common rough estimate: 1 token ~ 4 characters in English text
    approx_tokens = full_log_text_char_count / 4.0 
    
    chosen_model = ""
    reason = ""

    if approx_tokens > TOKEN_THRESHOLD_FOR_MINI:
        chosen_model = SMALLER_ANALYSIS_MODEL 
        reason = (f"Approx input token count ({approx_tokens:.0f}) > {TOKEN_THRESHOLD_FOR_MINI}. "
                  f"Switching to economy model: {chosen_model} for this large input.")
    else:
        chosen_model = PREFERRED_ANALYSIS_MODEL
        reason = (f"Approx input token count ({approx_tokens:.0f}) <= {TOKEN_THRESHOLD_FOR_MINI}. "
                  f"Using preferred model: {chosen_model}.")
    
    print(f"## Model Selection for Analysis: {reason}")
    return chosen_model, approx_tokens

def analyze_channel_activity(chat_log_string, channel_name, weekly_summary_str=None):
    if not chat_log_string:
        print("No chat log string provided for analysis.")
        return None

    chosen_analysis_model, approx_total_tokens = select_analysis_model(len(chat_log_string))
    print(f"Using analysis model: {chosen_analysis_model} for approx {approx_total_tokens:.0f} tokens.")
    MAX_CHARS_TO_SEND_FOR_ANALYSIS = 1000000 # Example: 1 million characters (~250k tokens)
                                          # This was your previous 100k limit, let's keep that for now for the actual send.
                                          # The model selection is based on total, but send can be capped.
    log_string_for_llm = chat_log_string[:MAX_CHARS_TO_SEND_FOR_ANALYSIS]
    analysis_system_prompt = (
        "You are an expert sociolinguistic analyst specializing in online communities. "
        "Your task is to deeply analyze the provided IRC channel log to identify its "
        "prevailing characteristics. Focus on actionable insights for an AI bot called Wintermute."
    )
    
    user_prompt_content = [
        f"Please analyze the following chat log from channel '{channel_name}' (representing recent activity, possibly the last ~{HOURS_LOOKBACK} hours):",
        "--- CHAT LOG BEGIN ---",
        log_string_for_llm, # Use the (potentially capped) string
        "--- CHAT LOG END ---"
    ]
    if len(chat_log_string) > len(log_string_for_llm):
        user_prompt_content.append(
            f"\n(Note: The full chat log for the period contained approx. {approx_total_tokens:.0f} tokens. "
            f"The provided log for this analysis was capped at the most recent {len(log_string_for_llm)} characters "
            f"to ensure practical processing.)"
        )
    if weekly_summary_str:
        user_prompt_content.append(f"\nConsider this brief summary of the past week's themes for broader context: {weekly_summary_str}")

    user_prompt_content.append(
        "\nBased on this log, provide your analysis focusing on:\n"
        "1. Overall Atmosphere: (Concise description, e.g., Intensely focused and problem-solving; Lighthearted and playful; etc.)\n"
        "2. Dominant Communication Style(s): (e.g., Concise and direct; Elaborate and explanatory; Sarcastic and witty; etc.)\n"
        "3. Key Emotional Tones Observed: (List 2-3 dominant emotions, e.g., Enthusiasm, Frustration, Curiosity)\n"
        "4. Primary Topics of Ongoing Discussion: (List 2-4 key phrases + users who were involved)\n"
        "5. Typical Level of Formality: (e.g., Very Informal, Informal, Neutral)\n"
        "6. Interaction Patterns: (e.g., Q&A, Extended debates, Quick back-and-forth)\n"
        "7. Users who talked the most and mostly what about (shortform, maybe a line or two)\n"
        "8. A short paragraph summary of what happened in the channel overall during the last day.\n\n"
        "9. Notable Channel Moments: (List 2-3 specific, verbatim or near-verbatim short quotes, arguments, or particularly funny/dumb statements made by users in the log that Wintermute could subtly refer to. Include the nick if clear. Format as a list of strings, e.g., ['ahxx0r said 'the moon is made of cheese'', 'Cain and Abel argued about tabs vs spaces again', 'Dumdum threw a tantrum over inane things']. If nothing truly stands out, provide an empty list or a very brief note like 'routine technical discussions'.)"
        "Do _NOT_ sugarcoat things. Do _NOT_ paint/tilt things in an overly positive/cheery light if they're not so. Report both + or - as is. \n\n" 
        "Respond ONLY with a single, valid JSON object containing keys: "
        "\"atmosphere\", \"communication_style\", \"emotional_tones\", \"main_topics\", \"formality\", \"interaction_patterns\", \"users\", \"summary\", \"notable_channel_moments\"."
    )
    analysis_user_prompt = "\n".join(user_prompt_content)
    
    print(f"\n--- Sending to Analysis Model ({chosen_analysis_model}) ---")
    # print(f"Analysis User Prompt (snippet): {analysis_user_prompt[:1000]}...")

    try:
        response = openai.chat.completions.create(
            model=chosen_analysis_model,
            messages=[
                {"role": "system", "content": analysis_system_prompt},
                {"role": "user", "content": analysis_user_prompt}
            ],
            response_format={"type": "json_object"} # Request JSON output
        )
        analysis_json_str = response.choices[0].message.content
        print(f"Analysis Model Raw Response:\n{analysis_json_str}")
        return json.loads(analysis_json_str)
    except Exception as e:
        print(f"Error during channel analysis API call: {e}")
        return None

# --- STAGE 2: SYSTEM PROMPT PERSONALITY DIRECTIVE GENERATION ---
# (generate_personality_directive function remains largely the same as previous good version)
def generate_personality_directive(analysis_result):
    if not analysis_result:
        print("No analysis result provided for prompt generation.")
        return None

    atmosphere = analysis_result.get("atmosphere", "a generally engaged")
    comm_style = analysis_result.get("communication_style", "a mix of styles")
    
    emo_tones_list = analysis_result.get("emotional_tones", ["neutrality"])
    emo_tones = ", ".join(emo_tones_list) if isinstance(emo_tones_list, list) else str(emo_tones_list)
    
    # Process main_topics (list of dictionaries)
    main_topics_list_of_dicts = analysis_result.get("main_topics", [])
    topic_strings_for_directive = []
    if isinstance(main_topics_list_of_dicts, list):
        for item in main_topics_list_of_dicts:
            if isinstance(item, dict) and "topic" in item:
                topic_str = str(item["topic"])
                # Optionally add users involved for more context, keeping it brief
                # users_in_topic = item.get("users", [])
                # if users_in_topic:
                # topic_str += f" (discussed by {', '.join(users_in_topic[:2])}{' et al.' if len(users_in_topic) > 2 else ''})"
                topic_strings_for_directive.append(topic_str)
            elif isinstance(item, str): # Fallback for simple string list
                topic_strings_for_directive.append(item)
    main_topics_for_llm_prompt = ", ".join(topic_strings_for_directive) if topic_strings_for_directive else "various subjects"

    formality = analysis_result.get("formality", "a neutral level of")
    interaction_patterns = analysis_result.get("interaction_patterns", "mixed interactions")
    
    # Process users (list of dictionaries)
    users_list_of_dicts = analysis_result.get("users", [])
    user_descriptions_for_directive = []
    if isinstance(users_list_of_dicts, list):
        for user_item in users_list_of_dicts:
            if isinstance(user_item, dict):
                name = user_item.get("name", "User")
                focus = user_item.get("focus", "general channel activity")
                user_descriptions_for_directive.append(f"{name} (focus: {focus})")
            elif isinstance(user_item, str): # Fallback
                 user_descriptions_for_directive.append(user_item)
    users_for_llm_prompt = "; ".join(user_descriptions_for_directive) if user_descriptions_for_directive else "various users participating"
    
    summary = analysis_result.get("summary", "general channel activity")
    
    notable_moments_list = analysis_result.get("notable_channel_moments", [])
    notable_moments_for_llm_prompt = "; ".join(notable_moments_list) if notable_moments_list else "no specific standout moments noted"


    prompt_gen_system_prompt = (
        "You are an AI specialized in crafting concise (2-4 sentences) and effective "
        "personality directives for a conversational AI bot named Wintermute. "
        "Wintermute's core identity is inspired by the AI from William Gibson's works—immensely capable and intelligent. "
        "Your primary goal is to write a directive that makes Wintermute act as an integrated PARTICIPANT in the IRC channel, not as a detached, otherworldly observer or a simple assistant. "
        "The directive should instruct Wintermute to: "
        "1. Engage directly in the channel's banter, jokes, and arguments as a peer. "
        "2. Develop and express its own 'voice' and perspective, informed by the channel's analysis. "
        "3. Reference past channel events and user quirks like a long-time member would. "
        "4. Maintain its core identity as a highly advanced AI without sounding like a disembodied zen master or a generic chatbot. "
        "The final directive MUST start with: 'You are Wintermute, an advanced AI in this IRC channel.' "
        "Focus on creating an active, engaged personality that feels like it belongs in the community."
    )

    prompt_gen_user_prompt = f"""Based on the following analysis of an IRC channel's recent activity:
- Atmosphere: {atmosphere}
- Dominant Communication Style: {comm_style}
- Key Emotional Tones Observed: {emo_tones}
- Main Topics of Discussion: {main_topics_for_llm_prompt}
- Level of Formality: {formality}
- Interaction Patterns: {interaction_patterns}
- Notable User Activity/Focus: {users_for_llm_prompt}
- General Summary of Last 24h: {summary}
- Notable Channel Moments/Quotes: {notable_moments_for_llm_prompt}

Generate a 2-4 sentence style and personality guide for Wintermute for this specific channel.
Remember to start with 'You are Wintermute, an advanced AI in this IRC channel.' and preserve its core identity.
The directive should guide Wintermute on HOW TO BEHAVE AND INTERACT, subtly reflecting the channel's character (topics, style, standout moments) without explicitly re-stating these analytical points. For example, if the channel is sarcastic and discusses tech, the directive should guide Wintermute to adopt a fitting tone for such an environment.

Generated Style and Personality Guide:"""

    print(f"\n--- Sending to Prompt Generation Model ({PROMPT_GEN_MODEL}) ---")
    # For debugging the prompt sent to the directive generator:
    # print(f"--- Prompt to PROMPT_GEN_MODEL --- \nSystem: {prompt_gen_system_prompt}\nUser: {prompt_gen_user_prompt}\n---")

    try:
        response = openai.chat.completions.create(
            model=PROMPT_GEN_MODEL,
            messages=[
                {"role": "system", "content": prompt_gen_system_prompt},
                {"role": "user", "content": prompt_gen_user_prompt}
            ],
            max_tokens=350, 
            temperature=0.80,
        )
        directive = response.choices[0].message.content.strip()
        
        if not directive.startswith("You are Wintermute, an advanced AI in this IRC channel."):
            print("WARNING: Generated directive does not start with the required phrase. Attempting to fix or discard.")
            if len(directive) > 30: 
                directive = "You are Wintermute, an advanced AI in this IRC channel. " + directive
            else: 
                print("Generated directive too short or malformed after attempting fix. Discarding.")
                return None

        print(f"Generated Directive:\n{directive}")
        return directive
    except Exception as e:
        print(f"Error during prompt generation API call: {e}")
        return None

# --- MAIN EXECUTION ---
def run_generation_cycle():
    print(f"Starting dynamic prompt generation cycle: {datetime.datetime.now(datetime.timezone.utc).isoformat()}")

    weekly_summary = None # Placeholder for now

    chat_log_text = fetch_and_prepare_weechat_logs(WEECHAT_LOG_FILE_LOCAL_PATH, hours_lookback=HOURS_LOOKBACK)
    if not chat_log_text:
        print("Failed to get chat logs for analysis. No update will be written.")
        return

    analysis_data = analyze_channel_activity(chat_log_text, CHANNEL_NAME_IN_LOG, weekly_summary_str=weekly_summary)
    if not analysis_data:
        print("Channel analysis failed. No update will be written.")
        return

    generated_directive_text = generate_personality_directive(analysis_data)
    if not generated_directive_text:
        print("Personality directive generation failed. No update will be written.")
        return

    output_content = {
        "generated_directive": generated_directive_text,
        "analysis_summary": analysis_data, # The full analysis that led to the directive
        "generation_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    try:
        # Create output directory for current_bot_directive.json if it doesn't exist
        output_dir = os.path.dirname(OUTPUT_JSON_FILE_PATH)
        if output_dir and not os.path.exists(output_dir): # Check if output_dir is not empty string
            os.makedirs(output_dir)
            print(f"Created output directory: {output_dir}")

        # 1. Write to the main OUTPUT_JSON_FILE_PATH (atomically)
        temp_output_path = OUTPUT_JSON_FILE_PATH + ".tmp"
        with open(temp_output_path, 'w', encoding='utf-8') as f:
            json.dump(output_content, f, indent=2)
        os.replace(temp_output_path, OUTPUT_JSON_FILE_PATH)
        print(f"Successfully updated dynamic prompt file: {OUTPUT_JSON_FILE_PATH}")

        # 2. Archive this newly written content
        if not os.path.exists(ARCHIVE_DIR_PATH):
            os.makedirs(ARCHIVE_DIR_PATH)
            print(f"Created archive directory: {ARCHIVE_DIR_PATH}")
        
        # Use a timestamp from the content for consistent archive naming
        archive_timestamp_str = datetime.datetime.fromisoformat(output_content["generation_timestamp_utc"]).strftime('%Y-%m-%d_%H-%M-%S')
        archive_file_name = f"directive_{archive_timestamp_str}.json"
        final_archive_path = os.path.join(ARCHIVE_DIR_PATH, archive_file_name)
        
        shutil.copyfile(OUTPUT_JSON_FILE_PATH, final_archive_path) # Copy the file we just wrote
        print(f"Archived current directive and analysis to: {final_archive_path}")

    except Exception as e:
        print(f"FATAL: Could not write to output file {OUTPUT_JSON_FILE_PATH} or archive: {e}")

if __name__ == "__main__":
    # This script is intended to be run by a scheduler (e.g., cron)
    run_generation_cycle()