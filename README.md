# COS484-project

NLP project using ELMo for the [BERT-ATTACK](https://www.aclweb.org/anthology/2020.emnlp-main.500.pdf) algorithm

!python bertattack_comb.py --subs gpt2 --word_imp --data_path data_defense/imdb_1k.tsv --mlm_path bert-base-uncased --tgt_path textattack/bert-base-uncased-imdb --use_sim_mat 0 --output_dir data_defense/imdb_logs.tsv --num_label 2 --k 20 --start 0 --end 500 --threshold_pred_score 0
