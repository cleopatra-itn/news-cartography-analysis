import time
import sys, getopt
from os import listdir
from os.path import isfile, join
import entity_extraction
import json
import csv
import file_utils

def get_files(directory):
    files = [f for f in listdir(directory) if isfile(join(directory, f))]
    return files

def process(input_dir, output_dir, language):
    event_list = set()

    with open('event_KG.csv', "r") as csvfile:
        content = csv.reader(csvfile)
        for row in content:
            event_list.add(row[0])

    checkpoint_doc_list = []

    if not file_utils.path_exists(output_dir):
        # create the output dir
        file_utils.create_folder(output_dir)
    else:
        try:
            checkpoint_doc_list = file_utils.read_file_to_list(output_dir+'/checkpoint.txt')
        except:
            pass

    input_files = get_files(input_dir)

    print('Total number of docs:',len(input_files))
    print('Already processed :', len(checkpoint_doc_list))

    for file in input_files:

        if file in checkpoint_doc_list:
            continue

        file_content = file_utils.read_json_file(input_dir+'/'+file)
        text= file_content['text']

        while True:

            spacy_annotations = entity_extraction.get_spacy_annotations(text, language)
            wikifier_annotations = entity_extraction.get_wikifier_annotations(text, language)

            if wikifier_annotations['processed'] == True:

                linked_entities = entity_extraction.link_annotations(spacy_annotations, wikifier_annotations)
                linked_entities = entity_extraction.fix_entity_types(linked_entities, event_list)

                # save the content
                output = {"text": text, "entities": linked_entities}
                output_json = json.dumps(output)
                file_utils.save_string_to_file(output_json, output_dir+'/'+file)

                checkpoint_doc_list.append(file)

                file_utils.save_list_to_file(checkpoint_doc_list, output_dir+'/checkpoint.txt')

                print('Processed: ', len(checkpoint_doc_list),'/',len(input_files))

                break
            else:
                print("Rate limit is reached, sleeping for 10 mins")
                time.sleep(10 * 60)

def main(argv):
   input_dir = ''
   output_dir = ''
   language = ''
   try:
       opts, args = getopt.getopt(argv,"hi:o:l:",["i_dir=","o_dir=", "lang="])
   except getopt.GetoptError:
       print('preprocess_documents.py -i <input_dir> -o <output_dir> -l <language>')
       sys.exit(2)
   for opt, arg in opts:
       if opt == '-h':
           print('preprocess_documents.py -i <input_dir> -o <output_dir> -l <language>')
           sys.exit()
       elif opt in ("-i", "--i_dir"):
           input_dir = arg
       elif opt in ("-o", "--o_dir"):
           output_dir = arg
       elif opt in ("-l", "--lang"):
           language = arg

   print('Input dir: ', input_dir)
   print('Output dir: ', output_dir)
   print('Language: ', language)

   process(input_dir, output_dir, language)


if __name__ == "__main__":
   main(sys.argv[1:])