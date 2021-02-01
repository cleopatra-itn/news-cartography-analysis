# News Cartography Analysis

# Setup

Create a virtual environment with Python 3
```
python3 -m venv venv
```

Activate the virtual environment
```
source venv/bin/activate
```

Install the python libraries
```
pip3 install -r requirements.txt
```

Install Spacy English model
```
python3 -m spacy download en_core_web_sm
```

Install Spacy Portuguese model
```
python3 -m spacy download pt_core_news_sm
```

# Entity recognition and disambiguation

To start extraction process provide the following parameters, languages: English: en, Portuguese: pt:

```
python preprocess_documents.py -i input_dir -o output_dir -l en
```
