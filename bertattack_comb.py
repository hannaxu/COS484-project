# -*- coding: utf-8 -*-
# @Time    : 2020/6/10
# @Author  : Linyang Li
# @Email   : linyangli19@fudan.edu.cn
# @File    : attack.py


import warnings
import os

import torch
import torch.nn as nn
import json
from torch.utils.data import DataLoader, SequentialSampler, TensorDataset
from transformers import BertConfig, BertTokenizer
from transformers import BertForSequenceClassification, BertForMaskedLM
import copy
import argparse
import numpy as np

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
warnings.simplefilter(action='ignore', category=FutureWarning)

filter_words = ['a', 'about', 'above', 'across', 'after', 'afterwards', 'again', 'against', 'ain', 'all', 'almost',
                'alone', 'along', 'already', 'also', 'although', 'am', 'among', 'amongst', 'an', 'and', 'another',
                'any', 'anyhow', 'anyone', 'anything', 'anyway', 'anywhere', 'are', 'aren', "aren't", 'around', 'as',
                'at', 'back', 'been', 'before', 'beforehand', 'behind', 'being', 'below', 'beside', 'besides',
                'between', 'beyond', 'both', 'but', 'by', 'can', 'cannot', 'could', 'couldn', "couldn't", 'd', 'didn',
                "didn't", 'doesn', "doesn't", 'don', "don't", 'down', 'due', 'during', 'either', 'else', 'elsewhere',
                'empty', 'enough', 'even', 'ever', 'everyone', 'everything', 'everywhere', 'except', 'first', 'for',
                'former', 'formerly', 'from', 'hadn', "hadn't", 'hasn', "hasn't", 'haven', "haven't", 'he', 'hence',
                'her', 'here', 'hereafter', 'hereby', 'herein', 'hereupon', 'hers', 'herself', 'him', 'himself', 'his',
                'how', 'however', 'hundred', 'i', 'if', 'in', 'indeed', 'into', 'is', 'isn', "isn't", 'it', "it's",
                'its', 'itself', 'just', 'latter', 'latterly', 'least', 'll', 'may', 'me', 'meanwhile', 'mightn',
                "mightn't", 'mine', 'more', 'moreover', 'most', 'mostly', 'must', 'mustn', "mustn't", 'my', 'myself',
                'namely', 'needn', "needn't", 'neither', 'never', 'nevertheless', 'next', 'no', 'nobody', 'none',
                'noone', 'nor', 'not', 'nothing', 'now', 'nowhere', 'o', 'of', 'off', 'on', 'once', 'one', 'only',
                'onto', 'or', 'other', 'others', 'otherwise', 'our', 'ours', 'ourselves', 'out', 'over', 'per',
                'please', 's', 'same', 'shan', "shan't", 'she', "she's", "should've", 'shouldn', "shouldn't", 'somehow',
                'something', 'sometime', 'somewhere', 'such', 't', 'than', 'that', "that'll", 'the', 'their', 'theirs',
                'them', 'themselves', 'then', 'thence', 'there', 'thereafter', 'thereby', 'therefore', 'therein',
                'thereupon', 'these', 'they', 'this', 'those', 'through', 'throughout', 'thru', 'thus', 'to', 'too',
                'toward', 'towards', 'under', 'unless', 'until', 'up', 'upon', 'used', 've', 'was', 'wasn', "wasn't",
                'we', 'were', 'weren', "weren't", 'what', 'whatever', 'when', 'whence', 'whenever', 'where',
                'whereafter', 'whereas', 'whereby', 'wherein', 'whereupon', 'wherever', 'whether', 'which', 'while',
                'whither', 'who', 'whoever', 'whole', 'whom', 'whose', 'why', 'with', 'within', 'without', 'won',
                "won't", 'would', 'wouldn', "wouldn't", 'y', 'yet', 'you', "you'd", "you'll", "you're", "you've",
                'your', 'yours', 'yourself', 'yourselves']
filter_words = set(filter_words)


def get_sim_embed(embed_path, sim_path):
    id2word = {}
    word2id = {}

    with open(embed_path, 'r', encoding='utf-8') as ifile:
        for line in ifile:
            word = line.split()[0]
            if word not in id2word:
                id2word[len(id2word)] = word
                word2id[word] = len(id2word) - 1

    cos_sim = np.load(sim_path)
    return cos_sim, word2id, id2word


def get_data_cls(data_path):
    lines = open(data_path, 'r', encoding='utf-8').readlines()[1:]
    features = []
    for i, line in enumerate(lines):
        split = line.strip('\n').split('\t')
        label = int(split[-1])
        seq = split[0]

        features.append([seq, label])
    return features


class Feature(object):
    def __init__(self, seq_a, label):
        self.label = label
        self.seq = seq_a
        self.final_adverse = seq_a
        self.query = 0
        self.change = 0
        self.success = 0
        self.sim = 0.0
        self.changes = []


def _tokenize(seq, tokenizer):
    seq = seq.replace('\n', '').lower()
    words = seq.split(' ')

    sub_words = []
    keys = []
    index = 0
    for word in words:
        sub = tokenizer.tokenize(word)
        sub_words += sub
        keys.append([index, index + len(sub)])
        index += len(sub)

    return words, sub_words, keys


def _get_masked(words):
    len_text = len(words)
    masked_words = []
    for i in range(len_text - 1):
        masked_words.append(words[0:i] + ['[UNK]'] + words[i + 1:])
    # list of words
    return masked_words


def get_important_scores(words, tgt_model, orig_prob, orig_label, orig_probs, tokenizer, batch_size, max_length):
    masked_words = _get_masked(words)
    # list of text of masked words
    texts = [' '.join(words) for words in masked_words]
    all_input_ids = []
    all_masks = []
    all_segs = []
    for text in texts:
        inputs = tokenizer.encode_plus(
            text, None, add_special_tokens=True, max_length=max_length, )
        input_ids, token_type_ids = inputs["input_ids"], inputs["token_type_ids"]
        attention_mask = [1] * len(input_ids)
        padding_length = max_length - len(input_ids)
        input_ids = input_ids + (padding_length * [0])
        token_type_ids = token_type_ids + (padding_length * [0])
        attention_mask = attention_mask + (padding_length * [0])
        all_input_ids.append(input_ids)
        all_masks.append(attention_mask)
        all_segs.append(token_type_ids)
    seqs = torch.tensor(all_input_ids, dtype=torch.long)
    masks = torch.tensor(all_masks, dtype=torch.long)
    segs = torch.tensor(all_segs, dtype=torch.long)
    seqs = seqs.to('cuda')

    eval_data = TensorDataset(seqs)
    # Run prediction for full data
    eval_sampler = SequentialSampler(eval_data)
    eval_dataloader = DataLoader(
        eval_data, sampler=eval_sampler, batch_size=batch_size)
    leave_1_probs = []
    for batch in eval_dataloader:
        masked_input, = batch
        bs = masked_input.size(0)

        leave_1_prob_batch = tgt_model(masked_input)[0]  # B num-label
        leave_1_probs.append(leave_1_prob_batch)
    leave_1_probs = torch.cat(leave_1_probs, dim=0)  # words, num-label
    leave_1_probs = torch.softmax(leave_1_probs, -1)  #
    leave_1_probs_argmax = torch.argmax(leave_1_probs, dim=-1)
    import_scores = (orig_prob
                     - leave_1_probs[:, orig_label]
                     +
                     (leave_1_probs_argmax != orig_label).float()
                     * (leave_1_probs.max(dim=-1)[0] - torch.index_select(orig_probs, 0, leave_1_probs_argmax))
                     ).data.cpu().numpy()

    return import_scores

### GET SUBSTITUTION ###


def fast_get_substitutes(model, tgt_word, k):
    try:
        substitutes = [word[0]
                       for word in word_vectors.similar_by_word(tgt_word, topn=k)]
        return substitutes
    except:
        return None


def gpt2_get_substitutes(model, input_data, k):
    input_data = " ".join(input_data)
    return model.predict_next(input_data, k)


def glove_get_substitutes(model, tgt_word, k):
    try:
        substitutes = [word[0]
                       for word in word_vectors.similar_by_word(tgt_word, topn=k)]
        return substitutes
    except:
        return None


def get_substitutes(substitutes, tokenizer, mlm_model, substitutes_score=None, threshold=3.0):
    # substitutes L,k
    # from this matrix to recover a word
    words = []
    sub_len, k = substitutes.size()  # sub-len, k

    if sub_len == 0:
        return words

    elif sub_len == 1:
        for (i, j) in zip(substitutes[0], substitutes_score[0]):
            if threshold != 0 and j < threshold:
                break
            words.append(tokenizer._convert_id_to_token(int(i)))
    return words
### GET SUBSTITUTION ###


def attack(word_imp, subs, replace_model, feature, tgt_model, mlm_model, tokenizer, k, batch_size, max_length=512, cos_mat=None, w2i={}, i2w={}, threshold_pred_score=0.3):
    # MLM-process
    words, sub_words, keys = _tokenize(feature.seq, tokenizer)

    # original label
    inputs = tokenizer.encode_plus(
        feature.seq, None, add_special_tokens=True, max_length=max_length, )
    input_ids, token_type_ids = torch.tensor(
        inputs["input_ids"]), torch.tensor(inputs["token_type_ids"])
    attention_mask = torch.tensor([1] * len(input_ids))
    seq_len = input_ids.size(0)
    orig_probs = tgt_model(input_ids.unsqueeze(0).to('cuda'),
                           attention_mask.unsqueeze(0).to('cuda'),
                           token_type_ids.unsqueeze(0).to('cuda')
                           )[0].squeeze()
    orig_probs = torch.softmax(orig_probs, -1)
    orig_label = torch.argmax(orig_probs)
    current_prob = orig_probs.max()

    if orig_label != feature.label:
        feature.success = 3
        return feature

    sub_words = ['[CLS]'] + sub_words[:max_length - 2] + ['[SEP]']
    input_ids_ = torch.tensor([tokenizer.convert_tokens_to_ids(sub_words)])
    word_predictions = mlm_model(input_ids_.to('cuda'))[
        0].squeeze()  # seq-len(sub) vocab
    word_pred_scores_all, word_predictions = torch.topk(
        word_predictions, k, -1)  # seq-len k

    word_predictions = word_predictions[1:len(sub_words) + 1, :]
    word_pred_scores_all = word_pred_scores_all[1:len(sub_words) + 1, :]

    important_scores = get_important_scores(words, tgt_model, current_prob, orig_label, orig_probs,
                                            tokenizer, batch_size, max_length)
    feature.query += int(len(words))

### TEST HYPERPARAMETER WORD_IMP ###
    list_of_index = None
    if word_imp == 'mir':
        list_of_index = sorted(enumerate(important_scores),
                               key=lambda x: x[1], reverse=True)
    elif word_imp == 'lir':
        list_of_index = sorted(enumerate(important_scores),
                               key=lambda x: x[1], reverse=False)
    elif word_imp == 'rand':
        from random import shuffle
        shuffle(important_scores)
        list_of_index = important_scores
### END HYPERPARAMETER WORD_IMP ###

    # print(list_of_index)
    final_words = copy.deepcopy(words)

    for top_index in list_of_index:
        if feature.change > int(0.4 * (len(words))):
            feature.success = 1  # exceed
            return feature

        tgt_word = words[top_index[0]]
        if tgt_word in filter_words:
            continue
        if keys[top_index[0]][0] > max_length - 2:
            continue

        substitutes = word_predictions[keys[top_index[0]]
                                       [0]:keys[top_index[0]][1]]  # L, k
        word_pred_scores = word_pred_scores_all[keys[top_index[0]]
                                                [0]:keys[top_index[0]][1]]

### MODEL SELECTION ###
        if subs == "bert":
            substitutes = get_substitutes(
                substitutes, tokenizer, mlm_model, word_pred_scores, threshold_pred_score)
        elif subs == "glove":
            substitutes = glove_get_substitutes(replace_model, tgt_word, k)
            if not substitutes:
                continue
        elif subs == "gpt2":
            substitutes = gpt2_get_substitutes(
                replace_model, words[0:top_index[0]], k)
        elif subs == "fasttext":
            substitutes = fast_get_substitutes(replace_model, tgt_word, k)
### END MODEL SELECTION ###

        most_gap = 0.0
        candidate = None

        for substitute_ in substitutes:
            substitute = substitute_

            if substitute == tgt_word:
                continue  # filter out original word
            if '##' in substitute:
                continue  # filter out sub-word

            if substitute in filter_words:
                continue
            if substitute in w2i and tgt_word in w2i:
                if cos_mat[w2i[substitute]][w2i[tgt_word]] < 0.4:
                    continue
            temp_replace = final_words
            temp_replace[top_index[0]] = substitute
            temp_text = tokenizer.convert_tokens_to_string(temp_replace)
            inputs = tokenizer.encode_plus(
                temp_text, None, add_special_tokens=True, max_length=max_length, )
            input_ids = torch.tensor(
                inputs["input_ids"]).unsqueeze(0).to('cuda')
            seq_len = input_ids.size(1)
            temp_prob = tgt_model(input_ids)[0].squeeze()
            feature.query += 1
            temp_prob = torch.softmax(temp_prob, -1)
            temp_label = torch.argmax(temp_prob)

            if temp_label != orig_label:
                feature.change += 1
                final_words[top_index[0]] = substitute
                feature.changes.append(
                    [keys[top_index[0]][0], substitute, tgt_word])
                feature.final_adverse = temp_text
                feature.success = 4
                return feature
            else:

                label_prob = temp_prob[orig_label]
                gap = current_prob - label_prob
                if gap > most_gap:
                    most_gap = gap
                    candidate = substitute

        if most_gap > 0:
            feature.change += 1
            feature.changes.append(
                [keys[top_index[0]][0], candidate, tgt_word])
            current_prob = current_prob - most_gap
            final_words[top_index[0]] = candidate

    feature.final_adverse = (tokenizer.convert_tokens_to_string(final_words))
    feature.success = 2
    return feature


def evaluate(features):
    do_use = 0
    use = None
    sim_thres = 0
    # evaluate with USE

    if do_use == 1:
        cache_path = ''
        import tensorflow as tf
        import tensorflow_hub as hub

        class USE(object):
            def __init__(self, cache_path):
                super(USE, self).__init__()

                self.embed = hub.Module(cache_path)
                config = tf.ConfigProto()
                config.gpu_options.allow_growth = True
                self.sess = tf.Session()
                self.build_graph()
                self.sess.run(
                    [tf.global_variables_initializer(), tf.tables_initializer()])

            def build_graph(self):
                self.sts_input1 = tf.placeholder(tf.string, shape=(None))
                self.sts_input2 = tf.placeholder(tf.string, shape=(None))

                sts_encode1 = tf.nn.l2_normalize(
                    self.embed(self.sts_input1), axis=1)
                sts_encode2 = tf.nn.l2_normalize(
                    self.embed(self.sts_input2), axis=1)
                self.cosine_similarities = tf.reduce_sum(
                    tf.multiply(sts_encode1, sts_encode2), axis=1)
                clip_cosine_similarities = tf.clip_by_value(
                    self.cosine_similarities, -1.0, 1.0)
                self.sim_scores = 1.0 - tf.acos(clip_cosine_similarities)

            def semantic_sim(self, sents1, sents2):
                sents1 = [s.lower() for s in sents1]
                sents2 = [s.lower() for s in sents2]
                scores = self.sess.run(
                    [self.sim_scores],
                    feed_dict={
                        self.sts_input1: sents1,
                        self.sts_input2: sents2,
                    })
                return scores[0]

            use = USE(cache_path)

    acc = 0
    origin_success = 0
    total = 0
    total_q = 0
    total_change = 0
    total_word = 0
    for feat in features:
        if feat.success > 2:

            if do_use == 1:
                sim = float(use.semantic_sim([feat.seq], [feat.final_adverse]))
                if sim < sim_thres:
                    continue

            acc += 1
            total_q += feat.query
            total_change += feat.change
            total_word += len(feat.seq.split(' '))

            if feat.success == 3:
                origin_success += 1

        total += 1

    suc = float(acc / total)

    query = float(total_q / acc)
    change_rate = float(total_change / total_word)

    origin_acc = 1 - origin_success / total
    after_atk = 1 - suc

    print('acc/aft-atk-acc {:.6f}/ {:.6f}, query-num {:.4f}, change-rate {:.4f}'.format(
        origin_acc, after_atk, query, change_rate))


def dump_features(features, output):
    outputs = []

    for feature in features:
        outputs.append({'label': feature.label,
                        'success': feature.success,
                        'change': feature.change,
                        'num_word': len(feature.seq.split(' ')),
                        'query': feature.query,
                        'changes': feature.changes,
                        'seq_a': feature.seq,
                        'adv': feature.final_adverse,
                        })
    output_json = output
    json.dump(outputs, open(output_json, 'w'), indent=2)

    print('finished dump')


def run_attack():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_path", type=str, help="./data/xxx")
    parser.add_argument("--mlm_path", type=str, help="xxx mlm")
    parser.add_argument("--tgt_path", type=str, help="xxx classifier")
    parser.add_argument(
        "--subs", type=str, help="xxx model for substitution: bert, gpt2, fasttext, glove")
    parser.add_argument("--word_imp", type=str,
                        help="word importance: mir, rand, lir")

    parser.add_argument("--output_dir", type=str, help="train file")
    parser.add_argument("--use_sim_mat", type=int,
                        help='whether use cosine_similarity to filter out atonyms')
    parser.add_argument("--start", type=int,
                        help="start step, for multi-thread process")
    parser.add_argument("--end", type=int,
                        help="end step, for multi-thread process")
    parser.add_argument("--num_label", type=int, )
    parser.add_argument("--k", type=int, )
    parser.add_argument("--threshold_pred_score", type=float, )

    args = parser.parse_args()
    data_path = str(args.data_path)
    mlm_path = str(args.mlm_path)
    tgt_path = str(args.tgt_path)
    subs = str(args.subs)
    word_imp = str(args.word_imp)
    output_dir = str(args.output_dir)
    num_label = args.num_label
    k = args.k
    start = args.start
    end = args.end
    threshold_pred_score = args.threshold_pred_score

    print('start process')

    tokenizer_mlm = BertTokenizer.from_pretrained(mlm_path, do_lower_case=True)
    tokenizer_tgt = BertTokenizer.from_pretrained(tgt_path, do_lower_case=True)

    config_atk = BertConfig.from_pretrained(mlm_path)
    mlm_model = BertForMaskedLM.from_pretrained(mlm_path, config=config_atk)
    mlm_model.to('cuda')

    config_tgt = BertConfig.from_pretrained(tgt_path, num_labels=num_label)
    tgt_model = BertForSequenceClassification.from_pretrained(
        tgt_path, config=config_tgt)
    tgt_model.to('cuda')
    features = get_data_cls(data_path)
    print('loading sim-embed')

    if args.use_sim_mat == 1:
        cos_mat, w2i, i2w = get_sim_embed(
            'data_defense/counter-fitted-vectors.txt', 'data_defense/cos_sim_counter_fitting.npy')
    else:
        cos_mat, w2i, i2w = None, {}, {}

    print('finish get-sim-embed')
    features_output = []

### BEGIN SUBS MODEL SETUP ###
    replace_model = None
    if subs == "glove":
        import gensim.downloader as api
        replace_model = api.load("glove-wiki-gigaword-100")
    elif subs == "gpt2":
        from next_word_prediction import GPT2
        replace_model = GPT2()
    elif subs == "fasttext":
        from gensim.models import KeyedVectors
        replace_model = KeyedVectors.load_word2vec_format(
            '../drive/MyDrive/wiki-news-300d-1M.vec')
### END SUBS MODEL SETUP ###

    with torch.no_grad():
        for index, feature in enumerate(features[start:end]):
            seq_a, label = feature
            feat = Feature(seq_a, label)
            print('\r number {:d} '.format(index) + tgt_path, end='')
            # print(feat.seq[:100], feat.label)
            feat = attack(word_imp, subs, replace_model, feat, tgt_model, mlm_model, tokenizer_tgt, k, batch_size=32, max_length=512,
                          cos_mat=cos_mat, w2i=w2i, i2w=i2w, threshold_pred_score=threshold_pred_score)

            # print(feat.changes, feat.change, feat.query, feat.success)
            if feat.success > 2:
                print('success', end='')
            else:
                print('failed', end='')
            features_output.append(feat)

    evaluate(features_output)

    dump_features(features_output, output_dir)


if __name__ == '__main__':
    run_attack()
