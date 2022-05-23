import os
import torch
import torch.optim as optim
from torch.utils.data import DataLoader
from modules.trainer import Trainer
from modules.utils import load_yaml, save_yaml, get_logger, make_directory
from modules.earlystoppers import LossEarlyStopper
from modules.metrics import Hitrate
from modules.recorders import PerformanceRecorder
from datetime import datetime, timezone, timedelta
import numpy as np
import random
from model.model import ElectraSummarizer
from model.model import FunnelSummarizer
from model.model import BertSummarizer
from modules.dataset import ElectraCustomDataset,ElectraCCustomDataset
from modules.dataset import FunnelCustomDataset,FunnelCCustomDataset
from modules.dataset import BertCustomDataset,BertCCustomDataset
import json

# CONFIG
MODEL_NAME='funnel'
PROJECT_DIR = os.path.dirname(os.path.abspath('./triain.ipynb'))
ROOT_PROJECT_DIR = os.path.dirname(PROJECT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, f'data/{MODEL_NAME}')
TRAIN_CONFIG_PATH = os.path.join(PROJECT_DIR, f'config/{MODEL_NAME}/train_config.yml')
config = load_yaml(TRAIN_CONFIG_PATH)

# SEED
RANDOM_SEED = config['SEED']['random_seed']

# TRAIN
EPOCHS = config['TRAIN']['num_epochs']
# EPOCHS = 1
BATCH_SIZE = config['TRAIN']['batch_size']
LEARNING_RATE = config['TRAIN']['learning_rate']
EARLY_STOPPING_PATIENCE = config['TRAIN']['early_stopping_patience']
OPTIMIZER = config['TRAIN']['optimizer']
SCHEDULER = config['TRAIN']['scheduler']
MOMENTUM = config['TRAIN']['momentum']
WEIGHT_DECAY = config['TRAIN']['weight_decay']
LOSS_FN = config['TRAIN']['loss_function']



# PERFORMANCE RECORD
PERFORMANCE_RECORD_DIR = os.path.join(PROJECT_DIR, 'results', 'train', MODEL_NAME)
PERFORMANCE_RECORD_COLUMN_NAME_LIST = config['PERFORMANCE_RECORD']['column_list']
# Set random seed
torch.manual_seed(RANDOM_SEED)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False
np.random.seed(RANDOM_SEED)
random.seed(RANDOM_SEED)
# Set device
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# Set train result directory
make_directory(PERFORMANCE_RECORD_DIR)

# Set system logger
system_logger = get_logger(name='train',
                           file_path=os.path.join(PERFORMANCE_RECORD_DIR, 'train_log.log'))

# Load dataset & dataloader
train_dataset = FunnelCustomDataset(data_dir=DATA_DIR, mode='train')
validation_dataset = FunnelCustomDataset(data_dir=DATA_DIR, mode='val')
train_dataloader = DataLoader(dataset=train_dataset, batch_size=BATCH_SIZE, shuffle=True)
validation_dataloader = DataLoader(dataset=validation_dataset, batch_size=BATCH_SIZE, shuffle=False)

# Load Model
model = FunnelSummarizer().to(device)
system_logger.info('===== Review Model Architecture =====')
system_logger.info(f'{model} \n')

# Set optimizer, scheduler, loss function, metric function
optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
#optimizer = optim.SGD(model.parameters(), lr=LEARNING_RATE, momentum=0.7)

scheduler = optim.lr_scheduler.OneCycleLR(optimizer=optimizer, pct_start=0.1, div_factor=1e5, max_lr=config['TRAIN']['learning_rate'], epochs=100, total_steps=100, verbose=True)
# scheduler = optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer=optimizer, T_0=4, verbose=True)
loss_fn = torch.nn.BCELoss(reduction='none')

# Set metrics
metric_fn = Hitrate

# Set trainer
trainer = Trainer(model, device, loss_fn, metric_fn, optimizer, scheduler, logger=system_logger)

# Set earlystopper
early_stopper = LossEarlyStopper(patience=EARLY_STOPPING_PATIENCE, verbose=True, logger=system_logger)

# Set performance recorder
key_column_value_list = [
    MODEL_NAME,
    EARLY_STOPPING_PATIENCE,
    BATCH_SIZE,
    EPOCHS,
    LEARNING_RATE,
    WEIGHT_DECAY,
    RANDOM_SEED]

performance_recorder = PerformanceRecorder(column_name_list=PERFORMANCE_RECORD_COLUMN_NAME_LIST,
                                           record_dir=PERFORMANCE_RECORD_DIR,
                                           key_column_value_list=key_column_value_list,
                                           logger=system_logger,
                                           model=model,
                                           optimizer=optimizer,
                                           scheduler=scheduler)

# Save config yaml file
save_yaml(os.path.join(PERFORMANCE_RECORD_DIR, 'train_config.yaml'), config)

criterion = 0
for epoch_index in range(EPOCHS):
    trainer.train_epoch(train_dataloader, epoch_index=epoch_index)
    trainer.validate_epoch(validation_dataloader, epoch_index=epoch_index)
    # Performance record - csv & save elapsed_time
    performance_recorder.add_row(epoch_index=epoch_index,
                                 train_loss=trainer.train_mean_loss,
                                 validation_loss=trainer.val_mean_loss,
                                 train_score=trainer.train_score,
                                 validation_score=trainer.validation_score)

    # Performance record - plot
#     performance_recorder.save_performance_plot(final_epoch=epoch_index)

    # early_stopping check
    early_stopper.check_early_stopping(loss=trainer.val_mean_loss)

    if early_stopper.stop:
        print('Early stopped')
        break

#     if trainer.validation_score > criterion:
#         criterion = trainer.validation_score
#         performance_recorder.weight_path = os.path.join(PERFORMANCE_RECORD_DIR, 'best.pt')
#         performance_recorder.save_weight()
    if trainer.val_mean_loss < criterion or epoch_index == 0:
        print(f'improved {criterion} --> {trainer.val_mean_loss}')
        criterion = trainer.val_mean_loss
        performance_recorder.weight_path = os.path.join(PERFORMANCE_RECORD_DIR, 'best.pt')
        performance_recorder.save_weight()