# Predestination - AI Visual Scheduler

Predestination is a Flask-based visual scheduler that integrates deeply with Google Calendar and uses Google Gemini to automatically break down and schedule your daily tasks into free time slots.

## Setup Instructions

1. **Create and Activate a Virtual Environment** (optional but recommended):

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   ```

2. **Install Dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   Copy the provided `.env.example` file to create a `.env` file:

   ```bash
   cp .env.example .env
   ```

   _Make sure to fill in your `GEMINI_API_KEY`, `GOOGLE_CLIENT_ID`, and `GOOGLE_CLIENT_SECRET`._

4. **Run the Application**:

   ```bash
   python app.py
   ```

5. **Access the Web Interface**:
   Open your browser and navigate to `http://127.0.0.1:8000`.

## Features

- **Visual Timeline**: Drag to create slots, interact with your daily tasks visually.
- **AI Task Breakdown**: Click the "✨ AI Planner" button, type a task (e.g., "Set up a new GitHub repo"), and Gemini will break it down into steps and find free time bounds for it securely locally.
- **Google Calendar Sync**: Connect your Google Calendar via OAuth to instantly pull your day's busy blocks. The AI will avoid putting tasks over existing GCAL meetings.
- **Pending AI Tasks**: Accept AI-placed tasks to push them live to your Calendar, or Reject them to wipe them locally.
