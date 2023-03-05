# wintermute

a pair of three IRC chatbots that use OpenAI's curie-001, davinci-003(GPT3) and GPT3.5 APIs.

## Wintermute-3.5

This is what ChatGPT uses. Funnily, this also has to be modified **heavily** ( See the system prompt, modify it according to your needs (and/or with a jailbreak)) to work properly for it to not spam the channel with apologies about it being a chatbot and it not having any opinions. Context history is set to 4. (OpenAI's context limit is 4096 tokens, so 4 large messages work fine). Note that the contexts do not work for anything that is pastebinned (TODO).

## Wintermute-3

The bot uses davinci-003 model.

This actually works fine for the most part. It will still not give you many opinions, but at least it does not spam the channel with apologisms. Context history is set to 4.

## Legacy

The bot uses the older curie-001 model. Funnily, it is the most opinionated version of the bot. It is funny, weird, and arguably the most entertaining of the three.

### USAGE

- Replace channel names with channels in three places (You can just search for #channel).

- Replace the `if nick == "YOUR_OWN_NICKNAME_HERE":` with your own nickname.

- Replace the API key with your own.

- Run with `python wintermute_GPT35.py`

- use 'wintermute: xyz' for your questions. It will remember what you asked it before and what it responded with, so followup questions are easy.

## TODO:

- Consolidate passing channels to the bot into a single variable.

- Add a way for bot to ignore the channel history prior to it rejoining (or it just responds to last x messages that highlighted it)

- Remove context limitation from pastebin.
