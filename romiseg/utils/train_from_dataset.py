#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Nov  7 09:56:38 2019

@author: alienor
"""


import torch
from torch.optim import lr_scheduler
import torch.optim as optim
import torch.nn.functional as F
from collections import defaultdict

from romiseg.utils.dataloader_finetune import Dataset_im_label, plot_dataset, init_set


from torch.utils.tensorboard import SummaryWriter

from torch.utils.data import DataLoader

from torchvision import transforms

import os
import requests
import copy


import warnings
warnings.filterwarnings("ignore")

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print(device)

##################LOAD PRE-TRAINED WEIGHTS############

def download_file(url, target_dir):
    local_filename = url.split('/')[-1]
    # NOTE the stream=True parameter below
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(target_dir + '/' +local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192): 
                if chunk: # filter out keep-alive new chunks
                    f.write(chunk)
                    # f.flush()
    return local_filename

def save_and_load_model(weights_folder, model_segmentation_name):


    #if not already saved, download from database 
    if model_segmentation_name not in os.listdir(weights_folder):
        
        url = 'http://db.romi-project.eu/models/' + model_segmentation_name 
        
        download_file(url, weights_folder)
        
    model_segmentation = torch.load(weights_folder + '/' + model_segmentation_name)[0]
    
    try: 
        model_segmentation = model_segmentation.module
    except:
        model_segmentation = model_segmentation
            
    return model_segmentation






def dice_loss(pred, target, smooth = 1.):
    pred = pred.contiguous()
    target = target.contiguous()    

    intersection = (pred * target).sum(dim=2).sum(dim=2)
    
    loss = (1 - ((2. * intersection + smooth) / (pred.sum(dim=2).sum(dim=2) + target.sum(dim=2).sum(dim=2) + smooth)))
    
    return loss.mean()


def my_metric(outputs: torch.Tensor, labels: torch.Tensor):
    inds  = labels != 0
    bools = outputs[inds] == labels[inds]
    
    return torch.mean(bools.float())  # Or thresholded.mean() if you are interested in average across the batch



def calc_loss(pred, target, metrics, bce_weight=0.5):
    bce = F.binary_cross_entropy_with_logits(pred, target)

    pred = F.sigmoid(pred)
    dice = dice_loss(pred, target)

    loss = bce * bce_weight + dice * (1 - bce_weight)

    metrics['bce'] += bce.data.cpu().numpy() * target.size(0)
    metrics['dice'] += dice.data.cpu().numpy() * target.size(0)
    metrics['loss'] += loss.data.cpu().numpy() * target.size(0)

    return loss

def print_metrics(metrics, epoch_samples, phase):
    outputs = []
    for k in metrics.keys():
        outputs.append("{}: {:4f}".format(k, metrics[k] / epoch_samples))

    print("{}: {}".format(phase, ", ".join(outputs)))

def train_model(dataloaders, model, optimizer, scheduler, writer, num_epochs=25):
    L = []
    best_model_wts = copy.deepcopy(model.state_dict())
    best_loss = 1e10
    loss_test = []
    for epoch in range(num_epochs):
        #print('Epoch {}/{}'.format(epoch, num_epochs - 1))
        #print('-' * 10)
        print('Running epoch %d/%d'%(epoch, num_epochs), end="\r")

        #since = time.time()

        # Each epoch has a training and validation phase
        for phase in ['train', 'val']:
            if phase == 'train':
                scheduler.step()
                #for param_group in optimizer.param_groups:
                #    print("LR", param_group['lr'])

                model.train()  # Set model to training mode
            else:
                model.eval()   # Set model to evaluate mode

            metrics = defaultdict(float)
            epoch_samples = 0

            for inputs, labels in dataloaders[phase]:
                inputs = inputs.to(device)
                labels = labels.to(device)

                # zero the parameter gradients
                optimizer.zero_grad()

                # forward
                # track history if only in train
                with torch.set_grad_enabled(phase == 'train'):
                    outputs = model(inputs)
                    loss = calc_loss(outputs, labels, metrics)
                    #print(loss)
                    # backward + optimize only if in training phase
                    if phase == 'train':
                        loss.backward()
                        optimizer.step()

                # statistics
                epoch_samples += inputs.size(0)

            #print_metrics(metrics, epoch_samples, phase)
            epoch_loss = metrics['loss'] / epoch_samples
            L.append(epoch_loss)
            writer.add_scalar('train/crossentropy', epoch_loss, epoch)
        
            if phase == 'val':
                inputs, labels = next(iter(dataloaders[phase]))
                inputs = inputs.to(device)
                labels = labels.to(device)
                lab = torch.argmax(labels, dim = 1)
                # forward
                # track history if only in train
                outputs = model(inputs)
                out = torch.argmax(outputs, dim = 1)
                loss_test.append(my_metric(out, lab))
                
            # deep copy the model
            if phase == 'val' and epoch_loss < best_loss:
                #print("saving best model")
                best_loss = epoch_loss
                best_model_wts = copy.deepcopy(model.state_dict())
        
            #plot 4 images to visualize the data
            """
            images_tot = []
            titles_tot = []
            
            for i in range(num_classes):
                img = inputs[0]
                img = torchvision.transforms.ToPILImage()(img.detach().cpu())
                images_tot.append(img)
                titles_tot.append('image')
                img = outputs[0,i,:,:].int()
                img = torchvision.transforms.ToPILImage()(img.detach().cpu())
                images_tot.append(img)
                titles_tot.append(labels_names[i])
            g = alien.showclass()
            g.col_num = num_classes
            g.figsize = ((14, 8))
            g.title_list = titles_tot
            fig = g.showing(images_tot)        
            writer.add_figure('Segmented images', fig, epoch)
            """
    
        #time_elapsed = time.time() - since
        #print('{:.0f}m {:.0f}s'.format(time_elapsed // 60, time_elapsed % 60))

    #print('Best val loss: {:4f}'.format(best_loss))

    # load best model weights
        model.load_state_dict(best_model_wts)
    return model, L, loss_test






def fine_tune_train(path_train, path_val, weights_folder, label_names, tsboard_name,
                    model_segmentation_name, Sx, Sy, num_epochs, scan):
    num_classes = len(label_names)
    
    trans = transforms.Compose([
    transforms.CenterCrop((Sx, Sy)),
    transforms.ToTensor(),
])
    
    image_train, target_train = init_set('', path_train, 'jpg')
    train_dataset = Dataset_im_label(image_train, target_train, transform = trans) 
    batch_size = min(num_classes, len(image_train))
    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=1)
    
    image_val, target_val = init_set('', path_val, 'jpg')
    val_dataset = Dataset_im_label(image_val, target_val, transform = trans) 
    
    plot_dataset(train_loader, label_names, batch_size) #display training set
    
    print('Now the network will train on the data you annotated')

    
    batch_size = 2
       
    dataloaders = {
        'train': DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=0),
        'val': DataLoader(val_dataset, batch_size=batch_size, shuffle=True, num_workers=0)
        }
    
    
    model = save_and_load_model(weights_folder, model_segmentation_name)

    
    writer = SummaryWriter('test')#tsboard_name)


    a = list(model.children())
    for child in  a[0].children():
        for param in child.parameters():
            param.requires_grad = False
    
    optimizer_ft = optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=1e-4)
    
    exp_lr_scheduler = lr_scheduler.StepLR(optimizer_ft, step_size=30, gamma=0.1)
    
    
    model = train_model(dataloaders, model, optimizer_ft, exp_lr_scheduler, writer,  num_epochs = num_epochs)
    ext_name = '_finetune_' + scan + '_epoch%d.pt'%num_epochs
    new_model_name = model_segmentation_name[:-3] + ext_name

    torch.save(model, weights_folder + '/' + new_model_name)
    
    
    return model, new_model_name

    
# Prediction
def evaluate(inputs, model):

    with torch.no_grad():
        inputs.requires_grad = False
        # Get the first batch
        inputs = inputs.to(device)

        pred = model(inputs)
        # The loss functions include the sigmoid function.
        pred = F.sigmoid(pred)
        
    return pred
    