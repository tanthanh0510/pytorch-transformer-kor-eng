import time
import random
import os
from tqdm import tqdm

import torch
import torch.nn as nn
import torch.optim as optim

from utils import epoch_time
from model.optim import ScheduledAdam
from model.transformer import Transformer

random.seed(32)
torch.manual_seed(32)
torch.backends.cudnn.deterministic = True


class Trainer:
    def __init__(self, params, mode, train_iter=None, valid_iter=None, test_iter=None):
        self.params = params

        # Train mode
        if mode == 'test':
           self.test_iter = test_iter
        # Test mode
        else:
            self.train_iter = train_iter
            self.valid_iter = valid_iter

        self.model = Transformer(self.params)
        self.model.to(self.params.device)

        self.epoch = 0
        self.best_valid_loss = float('inf')

        # Scheduling Optimzer
        self.optimizer = ScheduledAdam(
            optim.Adam(self.model.parameters(), betas=(0.9, 0.98), eps=1e-9),
            hidden_dim=params.hidden_dim,
            warm_steps=params.warm_steps
        )

        if os.path.exists(self.params.save_model):
            train_state = torch.load(self.params.save_model)
            self.epochVal = train_state['epoch']
            self.best_valid_loss = train_state['best_valid_loss']

        if os.path.exists("modelTrain.pt"):
          train_state = torch.load("modelTrain.pt")
          self.model.load_state_dict(train_state['model'])
          self.optimizer.optimizer.load_state_dict(train_state['optimizer'])
          self.optimizer.current_steps = train_state['current_steps']
          self.optimizer.init_lr = train_state['init_lr']
          self.epoch = train_state['epoch']

        self.criterion = nn.CrossEntropyLoss(ignore_index=self.params.pad_idx)
        self.criterion.to(self.params.device)

    def train(self):
        print(f'The model has {self.model.count_params():,} trainable parameters')
        print(f'Epoch: {self.epoch}')
        print(f'Best_valid_loss: {self.best_valid_loss}')

        for epoch in range(self.epoch,self.params.num_epoch):
            self.model.train()
            epoch_loss = 0
            start_time = time.time()
            pbar = tqdm(self.train_iter, desc=f"Train on epoch {epoch}")
            for batch in pbar:
                # For each batch, first zero the gradients
                self.optimizer.zero_grad()
                source = batch.kor
                target = batch.eng

                # target sentence consists of <sos> and following tokens (except the <eos> token)
                output = self.model(source, target[:, :-1])[0]

                # ground truth sentence consists of tokens and <eos> token (except the <sos> token)
                output = output.contiguous().view(-1, output.shape[-1])
                target = target[:, 1:].contiguous().view(-1)
                # output = [(batch size * target length - 1), output dim]
                # target = [(batch size * target length - 1)]
                loss = self.criterion(output, target)
                loss.backward()

                # clip the gradients to prevent the model from exploding gradient
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.params.clip)

                self.optimizer.step()

                pbar.set_postfix(loss=loss.item())

                # 'item' method is used to extract a scalar from a tensor which only contains a single value.
                epoch_loss += loss.item()

            train_loss = epoch_loss / len(self.train_iter)
            valid_loss = self.evaluate()

            end_time = time.time()
            epoch_mins, epoch_secs = epoch_time(start_time, end_time)

            if valid_loss < self.best_valid_loss:
                self.best_valid_loss = valid_loss                
                # torch.save(self.model.state_dict(), self.params.save_model)
                torch.save({
                            'epoch': epoch,
                            'model': self.model.state_dict(),
                            'optimizer': self.optimizer.optimizer.state_dict(),
                            'best_valid_loss': self.best_valid_loss,
                            'current_steps': self.optimizer.current_steps,
                            'init_lr': self.optimizer.init_lr
                        }, self.params.save_model)

            print(f'Epoch: {epoch+1:02} | Epoch Time: {epoch_mins}m {epoch_secs}s')
            print(f'\tTrain Loss: {train_loss:.3f} | Val. Loss: {valid_loss:.3f}')

    def evaluate(self):
        self.model.eval()
        epoch_loss = 0

        with torch.no_grad():
            pbar = tqdm(self.valid_iter, desc=f"Evaluate: ")
            for batch in pbar:
                source = batch.kor
                target = batch.eng

                output = self.model(source, target[:, :-1])[0]

                output = output.contiguous().view(-1, output.shape[-1])
                target = target[:, 1:].contiguous().view(-1)

                loss = self.criterion(output, target)
                
                pbar.set_postfix(loss=loss.item())

                epoch_loss += loss.item()

        return epoch_loss / len(self.valid_iter)

    def inference(self):
        self.model.load_state_dict(torch.load(self.params.save_model))
        self.model.eval()
        epoch_loss = 0

        with torch.no_grad():
            for batch in self.test_iter:
                source = batch.kor
                target = batch.eng

                output = self.model(source, target[:, :-1])[0]

                output = output.contiguous().view(-1, output.shape[-1])
                target = target[:, 1:].contiguous().view(-1)

                loss = self.criterion(output, target)

                epoch_loss += loss.item()

        test_loss = epoch_loss / len(self.test_iter)
        print(f'Test Loss: {test_loss:.3f}')
