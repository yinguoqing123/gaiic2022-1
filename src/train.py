import torch
from torch import nn
from torch.nn import functional as F
from transformers import AutoModel, AutoConfig, BertModel, AutoTokenizer,  BertTokenizer
from torch.utils.data import DataLoader, SequentialSampler, ConcatDataset
import numpy as np
from dataset import MyDataSet
from model import MyModel
from utils import evaluate, EMA
from visualbert import DistilBertModel, DistilBertForMaskedLM
from lebert import BertModel, BertForMaskedLM


bert_name = 'sentence-transformers/clip-ViT-B-32-multilingual-v1'
config = AutoConfig.from_pretrained(bert_name)
state_dict = torch.load("../pretrained_model/clip-ViT-B-32-multilingual-v1.bin")
tokenizer = AutoTokenizer.from_pretrained(bert_name)
bert = DistilBertModel.from_pretrained(bert_name, state_dict=state_dict)


model = MyModel(bert)
model = model.cuda()

# ema = EMA(model)
# model.load_state_dict(torch.load("../model/model_best.pt.0.9480"))
# ema.register()


path_train = '../data/train/train_fine.txt.00'
path_coarse_train = '../data/train/train_coarse_trans.txt'
path_test = '../data/train/train_fine.txt.01'
path_coarse_noattr = '../data/train/train_coarse_noattr.txt.00'
path_testA = '../data/train/preliminary_testA.txt.pesu_label'
trainset = MyDataSet(path_train, tokenizer=tokenizer)
traincoarseset = MyDataSet(path_coarse_train, tokenizer=tokenizer, mode='coarse')
# trainset_testA = MyDataSet(path_testA, tokenizer=tokenizer)
traincoarsesetnoattr = MyDataSet(path_coarse_noattr, tokenizer=tokenizer, mode='coarse')

testset = MyDataSet(path_test, tokenizer=tokenizer)
path_coarse_noattr_test = '../data/train/train_coarse_noattr.txt.01'
testcoarsesetnoattr = MyDataSet(path_coarse_noattr_test, tokenizer=tokenizer, mode='coarse')
testunion = ConcatDataset([testset, testcoarsesetnoattr])
testsample = SequentialSampler(testunion)

trainsetunion = ConcatDataset([trainset, traincoarseset, traincoarsesetnoattr, testcoarsesetnoattr])
trainload = DataLoader(trainsetunion, batch_size=128, shuffle=True, collate_fn=trainset.collate_fn, num_workers=8)
testload = DataLoader(testunion, batch_size=128, sampler=testsample, collate_fn=testset.collate_fn, num_workers=8)

bert_parameters = list(model.bert.parameters())
other_no_decay_parameters = []
other_decay_parameters = []
for name, param in model.named_parameters():
    if 'bert' not in name and param.requires_grad:
        if 'bias' not in name:
            other_no_decay_parameters.append(param)
        else:
            other_decay_parameters.append(param)

p = [{'params': bert_parameters, 'lr': 5e-5}, {'params': other_no_decay_parameters, 'lr': 2e-4, 'weight_decay': 0.0001}, 
     {'params': other_decay_parameters, 'lr': 2e-4}]   
optimizer = torch.optim.Adam(p)
#lrscheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, 0.9)
scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, 'max', factor=0.7, patience=2)

best_p = evaluate(testload, model)
ema_first = True
for epoch in range(10):
    step = 0
    running_loss = 0
    for input in trainload:
        model.train()
        step += 1
        input = [f.cuda() for f in input]
        loss = model(input)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        # if epoch >= 4:
        #     ema.update()
        running_loss += loss.item()
        if step % 100 == 0:
            print(f"Epoch {epoch+1}, step {step+1} : {running_loss}")
            running_loss = 0
        
        if step % 300 == 0:
            
            # if epoch >= 4 and ema_first:
            #     ema.register()
            #     ema_first = False
                
            p = evaluate(testload, model)
            if p > best_p:
                best_p = p
                torch.save(model.state_dict(), f'../model/model_best.pt')
                # if not ema_first:
                #     ema.update()
                #     print(" ----  ema更新权重 -----")
                #     ema.apply_shadow()
                #     p = evaluate(testload, model)
                #     if p > best_p:
                #         best_p = p
                #         torch.save(model.state_dict(), f'../model/model_best.pt')
                #     ema.restore()
                
            scheduler.step(p)
            
    p = evaluate(testload, model)
    if p > best_p:
        best_p = p
        torch.save(model.state_dict(), f'../model/model_best.pt')
    
