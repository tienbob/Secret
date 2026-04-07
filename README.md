# Job Scraper Web Interface

A beautiful web dashboard to scrape job listings from LinkedIn, RubyOnRemote, and Wantedly.

## Features

- 🎨 Modern, responsive web interface
- 🔄 Real-time job status updates
- 📊 Job history tracking
- 📥 Direct CSV download
- 🎯 Support for LinkedIn, RubyOnRemote, and Wantedly
- ⚙️ Configurable scraping parameters

## Installation

1. Install the required dependencies:

```bash
pip install -r requirement.txt
```

2. Install Brave Browser (macOS):

```bash
ls "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
```

If that command fails, install Brave first or provide a custom path using `BRAVE_BINARY_PATH`.

## Usage

1. Start the web server:

```bash
python app.py
```

The app now binds to `127.0.0.1:5050` by default to avoid `localhost` conflicts on macOS.

Optional host/port override:

```bash
export HOST=127.0.0.1
export PORT=5050
python app.py
```

Optional environment variables:

```bash
export BROWSER=brave
export BRAVE_BINARY_PATH="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
```

Notes:
- `BROWSER` supports `brave` and `chrome`
- On macOS, the app defaults to `brave` when `BROWSER` is not set
- `BRAVE_BINARY_PATH` is only needed when Brave is installed in a non-default location

2. Open your browser and navigate to:

```url
http://127.0.0.1:5050
```

3. Fill in the scraping parameters:
  - **Platform**: Choose LinkedIn, RubyOnRemote, or Wantedly
   - **Job Keywords**: Enter the job title or keywords (e.g., "Ruby on Rails")
   - **Location**: Enter the location (e.g., "Japan", "US", "Europe")
   - **Max Pages**: Number of pages to scrape (1-10)
  - **Wantedly**: Configure Hiring Type, Order, and Only New filters
   - **Headless Mode**: Check to run browser in background (faster but you can't see the progress)

2. Click "Start Scraping" and monitor the progress in real-time

3. Download the results as CSV when the job completes

## How It Works

- **Frontend**: HTML/CSS/JavaScript with a modern, gradient design
- **Backend**: Flask web server that manages scraping jobs
- **Scraping**: Runs your `linkedin_scraper.py`, `rubyonremote_scraper.py`, and `wantedly_scraper.py` scripts
- **Real-time Updates**: Status polling updates the UI every 2 seconds

## File Structure

```python
.
├── app.py                   # Flask backend server
├── templates/
│   └── index.html           # Main web interface
├── static/
│   ├── style.css            # Styling
│   └── script.js            # Frontend logic
├── linkedin_scraper.py      # LinkedIn scraper (existing)
├── rubyonremote_scraper.py  # RubyOnRemote scraper (existing)
├── wantedly_scraper.py      # Wantedly scraper (existing)
└── requirements_web.txt     # Web dependencies
```

## Notes

- The web interface creates temporary copies of your scraper scripts with the configured parameters
- Output files are saved in the same directory with the naming pattern:
  - LinkedIn: `linkedin_{keywords}_{location}.csv`
  - RubyOnRemote: `rubyonremote_{keywords}_{location}.csv`
  - Wantedly: `wantedly_{keywords}_{location}.csv`
- Job history is kept in memory and will reset when you restart the server
