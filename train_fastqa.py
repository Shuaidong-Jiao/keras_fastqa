import os
from argparse import ArgumentParser

import numpy as np
from tensorflow.python import debug as tfdbg
from tensorflow.python.debug.lib.debug_data import has_inf_or_nan
from keras import backend as K
from keras.optimizers import Adam
from keras.callbacks import TensorBoard

from models import FastQA
from data import SquadReader, Iterator, SquadConverter, SquadEvalConverter, \
    Vocabulary, get_tokenizer
from trainer import SquadTrainer
from callbacks import FastQALRScheduler, FastQACheckpoint
from utils import dump_graph

from prepare_vocab import PAD_TOKEN, UNK_TOKEN


def main(args):
    token_to_index, index_to_token = Vocabulary.load(args.vocab_file)

    root, _ = os.path.splitext(args.vocab_file)
    basepath, basename = os.path.split(root)
    embed_path = f'{basepath}/embedding_{basename}.npy'
    embeddings = np.load(embed_path) if os.path.exists(embed_path) else None

    model = FastQA(len(token_to_index), args.embed, args.hidden,
                   question_limit=args.q_len, context_limit=args.c_len,
                   dropout=args.dropout, pretrained_embeddings=embeddings,
                   with_feature=not args.without_feature).build()
    opt = Adam()
    model.compile(optimizer=opt, loss_weights=[1, 1, 0, 0],
                  loss=['sparse_categorical_crossentropy', 'sparse_categorical_crossentropy', None, None])
    train_dataset = SquadReader(args.train_path)
    dev_dataset = SquadReader(args.dev_path)
    tokenizer = get_tokenizer(lower=args.lower, as_str=False)
    converter = SquadConverter(token_to_index, PAD_TOKEN, UNK_TOKEN, tokenizer,
                               question_max_len=args.q_len, context_max_len=args.c_len)
    eval_converter = SquadEvalConverter(
        token_to_index, PAD_TOKEN, UNK_TOKEN, tokenizer,
        question_max_len=args.q_len, context_max_len=args.c_len)
    train_generator = Iterator(train_dataset, args.batch, converter)
    dev_generator_loss = Iterator(dev_dataset, args.batch, converter, shuffle=False)
    dev_generator_f1 = Iterator(dev_dataset, args.batch, eval_converter, repeat=False, shuffle=False)
    trainer = SquadTrainer(model, train_generator, args.epoch, dev_generator_loss,
                           './models/fastqa.{epoch:02d}-{val_loss:.2f}.h5')
    trainer.add_callback(FastQALRScheduler(
        dev_generator_f1, val_answer_file=args.answer_path, steps=args.steps))
    trainer.add_callback(FastQACheckpoint('./models/fastqa.{steps:06d}.h5', steps=args.steps))
    if args.use_tensorboard:
        trainer.add_callback(TensorBoard(log_dir='./graph', batch_size=args.batch))
    history = trainer.run()
    dump_graph(history, 'loss_graph.png')


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('--epoch', default=100, type=int)
    parser.add_argument('--batch', default=32, type=int)
    parser.add_argument('--embed', default=300, type=int)
    parser.add_argument('--hidden', default=300, type=int)
    parser.add_argument('--dropout', default=0.5, type=float)
    parser.add_argument('--q-len', default=50, type=int)
    parser.add_argument('--c-len', default=650, type=int)
    parser.add_argument('--steps', default=1000, type=int)
    parser.add_argument('--train-path', default='./data/train-v1.1_train.txt', type=str)
    parser.add_argument('--dev-path', default='./data/train-v1.1_dev.txt', type=str)
    parser.add_argument('--answer-path', default='./data/train-v1.1_dev.json', type=str)
    parser.add_argument('--vocab-file', default='./data/vocab_question_context_min-freq10_max_size.pkl', type=str)
    parser.add_argument('--lower', default=False, action='store_true')
    parser.add_argument('--without-feature', default=False, action='store_true')
    parser.add_argument('--use-tensorboard', default=False, action='store_true')
    parser.add_argument('--debug', default=False, action='store_true')
    args = parser.parse_args()
    if args.debug:
        sess = K.get_session()
        sess = tfdbg.LocalCLIDebugWrapperSession(sess)
        sess.add_tensor_filter('has_inf_or_nan', has_inf_or_nan)
        K.set_session(sess)
    main(args)
