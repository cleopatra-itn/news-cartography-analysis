import logging
import spacy
import json
import urllib.parse
from urllib.request import Request
import requests
import time


def get_spacy_annotations(text, language):
    if language == "en":
        spacy_ner = spacy.load("en_core_web_sm")
    elif language == "de":
        spacy_ner = spacy.load("de_core_news_sm")
    elif language == "pt":
        spacy_ner = spacy.load("pt_core_news_sm")
    else:
        logging.error(f"Unsupported language {language}. Please use [en, de, pt]!")
        return []

    doc = spacy_ner(text)
    named_entities = []
    for ent in doc.ents:
        named_entities.append({
            'text': ent.text,
            'type': ent.label_,
            'start': ent.start_char,
            'end': ent.end_char,
            'cms': None,
        })
    return named_entities

def get_wikifier_annotations(text, language):
    threshold = 1.0
    endpoint = 'http://www.wikifier.org/annotate-article'
    language = language
    key = 'oafqnfoihieqdrsxazmvgynivwdddr'
    wikiDataClasses = 'false'
    wikiDataClassIds = 'true'
    includeCosines = 'false'
    data = urllib.parse.urlencode([("text", text), ("lang", language), ("userKey", key),
                                   ("pageRankSqThreshold", "%g" % threshold), ("applyPageRankSqThreshold", "true"),
                                   ("nTopDfValuesToIgnore", "200"), ("nWordsToIgnoreFromList", "200"),
                                   ("wikiDataClasses", wikiDataClasses), ("wikiDataClassIds", wikiDataClassIds),
                                   ("support", "true"), ("ranges", "false"), ("includeCosines", includeCosines),
                                   ("maxMentionEntropy", "3")])

    req = urllib.request.Request(endpoint, data=data.encode("utf8"), method="POST")
    with urllib.request.urlopen(req, timeout=60) as f:
        response = f.read()
        response = json.loads(response.decode("utf8"))
        if 'annotations' in response:
            return {'processed': True, 'annotations': response['annotations']}
        else:
            logging.error(f'No valid response: {response}')
            return {'processed': False, 'annotations': []}

def link_annotations(spacy_annotations, wikifier_annotations):
    POSSIBLE_SPACY_TYPES = ['PER', 'PERSON', 'FAC', 'ORG', 'GPE', 'LOC', 'EVENT', 'MISC']
    linked_entities = []
    for spacy_anno in spacy_annotations:
        # skip all entities with 0 or 1 characters or not in selected spacy types
        if len(spacy_anno['text']) < 2 or spacy_anno['type'] not in POSSIBLE_SPACY_TYPES:
            continue

        related_wikifier_entries = get_related_wikifier_entry(spacy_anno, wikifier_annotations)

        # if no valid wikifier entities were found, try to find entity based on string using <wbsearchentities>
        if len(related_wikifier_entries) < 1:
            # get wikidata id for extrated text string from spaCy NER
            entity_candidates = get_wikidata_entries(entity_string=spacy_anno['text'], limit_entities=1, language="en")

            # if also no match continue with next entity
            if len(entity_candidates) < 1:
                continue

            # take the first entry in wbsearchentities (most likely one)
            entity_candidate = {
                **{
                    'wd_id': entity_candidates[0]['id'],
                    'wd_label': entity_candidates[0]['label'],
                    'disambiguation': 'wbsearchentities'
                },
                **spacy_anno,
            }
        else:
            highest_PR = -1
            best_wikifier_candidate = related_wikifier_entries[0]
            for related_wikifier_entry in related_wikifier_entries:
                # print(related_wikifier_entry['title'], related_wikifier_entry['pageRank_occurence'])
                if related_wikifier_entry['pageRank_occurence'] > highest_PR:
                    best_wikifier_candidate = related_wikifier_entry
                    highest_PR = related_wikifier_entry['pageRank_occurence']

            entity_candidate = {
                **{
                    'wd_id': best_wikifier_candidate['wikiDataItemId'],
                    'wd_label': best_wikifier_candidate['secTitle'],
                    'disambiguation': 'wikifier'
                },
                **spacy_anno,
            }

        linked_entities.append(entity_candidate)

    return linked_entities


def get_related_wikifier_entry(spacy_anno, wikifier_annotations, char_tolerance=2, threshold=1e-4):
    # loop through entities found by wikifier
    aligned_candidates = []
    for wikifier_entity in wikifier_annotations['annotations']:
        if 'secTitle' not in wikifier_entity.keys() or 'wikiDataItemId' not in wikifier_entity.keys():
            continue

        wikifier_entity_occurences = wikifier_entity['support']

        # loop through all occurences of a given entity recognized by wikifier
        for wikifier_entity_occurence in wikifier_entity_occurences:

            if wikifier_entity_occurence['chFrom'] < spacy_anno['start'] - char_tolerance:
                continue

            if wikifier_entity_occurence['chTo'] > spacy_anno['end'] + char_tolerance:
                continue

            # apply very low threshold to get rid of annotation with very low confidence
            if wikifier_entity_occurence['pageRank'] < threshold:
                continue

            aligned_candidates.append({
                **wikifier_entity,
                **{
                    'pageRank_occurence': wikifier_entity_occurence['pageRank']
                }
            })

    return aligned_candidates


def get_entity_response(wikidata_id):
    query = """
            prefix schema: <http://schema.org/>
            PREFIX wikibase: <http://wikiba.se/ontology#>
            PREFIX wd: <http://www.wikidata.org/entity/>
            PREFIX wdt: <http://www.wikidata.org/prop/direct/>
            SELECT ?entity ?entityLabel ?entityDescription ?instance ?coordinate ?wikipedia_url ?wdimage
            WHERE {
              VALUES (?entity) {(wd:%s)}
              OPTIONAL { ?entity wdt:P31 ?instance . }
              OPTIONAL { ?entity wdt:P625 ?coordinate . }
              OPTIONAL { ?entity wdt:P18 ?wdimage . }
              OPTIONAL {
                ?wikipedia_url schema:about ?entity .
                ?wikipedia_url schema:inLanguage "en" . 
                ?wikipedia_url schema:isPartOf <https://en.wikipedia.org/> .
              }
              SERVICE wikibase:label {bd:serviceParam wikibase:language "en" .}
            }""" % wikidata_id

    res = get_response("https://query.wikidata.org/sparql", params={'format': 'json', 'query': query})

    if res:
        return res['results']
    else:
        return {'bindings': []}


def fix_entity_types(linked_entities, event_list):
    entity_info = {}

    for i in range(len(linked_entities)):
        wd_id = linked_entities[i]['wd_id']
        if wd_id not in entity_info:
            entity_info[wd_id] = get_entity_response(wikidata_id=wd_id)

        if wd_id in event_list:
            is_event = True
        else:
            is_event = False

        is_person = False
        is_location = False

        information = ["wikipedia_url", "entityDescription", "wdimage"]
        for b in entity_info[wd_id]["bindings"]:
            if "instance" in b and "value" in b["instance"] and b["instance"]["value"].endswith("/Q5"):
                is_person = True

            if "coordinate" in b and "value" in b["coordinate"]:
                is_location = True

            for info_tag in information:
                if info_tag in b and "value" in b[info_tag]:
                    linked_entities[i][info_tag] = b[info_tag]["value"]
                else:
                    linked_entities[i][info_tag] = ""

        if "wdimage" not in linked_entities[i] or linked_entities[i]["wdimage"] == "":  # set placeholder image
            linked_entities[i]["wdimage"] = "http://www.jennybeaumont.com/wp-content/uploads/2015/03/placeholder.gif"

        # set placeholder for card view
        linked_entities[i]["reference_images"] = [{"url": linked_entities[i]["wdimage"], "source": "wikidata"}]

        if is_location:
            linked_entities[i]["type"] = "LOCATION"
        if is_person:  # NOTE higher priority if an entity is an instance of person then it cannot be a location
            linked_entities[i]["type"] = "PERSON"
        if is_event:  # NOTE highest priority as the entity is covered by EventKG
            linked_entities[i]["type"] = "EVENT"
        if not (is_location or is_person or is_event):
            linked_entities[i]["type"] = "unknown"

    return linked_entities


def get_wikidata_entries(entity_string, limit_entities=7, language='en'):
    params = {
        'action': 'wbsearchentities',
        'format': 'json',
        'language': language,
        'search': entity_string,
        'limit': limit_entities
    }
    response = get_response('https://www.wikidata.org/w/api.php', params=params)
    if response:
        return response['search']
    else:
        return []


def get_response(url, params):
    i = 0
    try:
        r = requests.get(url, params=params, headers={'User-agent': 'your bot 0.1'})
        return r.json()
    except KeyboardInterrupt:
        raise
    except:
        logging.error(f'Got no response from wikidata. Retry {i}')  # TODO include reason r
        return {}
