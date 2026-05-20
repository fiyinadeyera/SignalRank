# Signal Rank

A simple event recommendation app that helps you find the best events for your goals using AI.

## What it does

Tell the app what you're looking for (networking, learning, dating, etc.) and it ranks events that match your goals. Uses Claude AI to intelligently filter and score events.

## How to use

1. Clone the repo
2. Install dependencies: `pip3 install flask anthropic requests python-dotenv`
3. Get API keys (free):
   - Anthropic: https://console.anthropic.com
   - Meetup: https://meetup.com/api
   - Ticketmaster: https://developer.ticketmaster.com
4. Create `.env` file with your keys:
   ```
   ANTHROPIC_API_KEY=your_key_here
   MEETUP_API_KEY=your_key_here
   TICKETMASTER_API_KEY=your_key_here
   ```
5. Run: `python3 app.py`
6. Open http://localhost:8000

## Built with

- Python + Flask (backend)
- Claude API (AI ranking)
- Meetup & Ticketmaster APIs (event data)
- Dark mode UI (frontend)

## First project built with Claude Code

This was built entirely using Claude Code as my coding assistant while learning to code.
