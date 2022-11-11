import os
import torch
from data.base_dataset import BaseDataset
from util.util import is_mesh_file, pad
from models.layers.mesh import Mesh
import pathlib
import csv
import numpy as np

class ClassificationData(BaseDataset):

    def __init__(self, opt):
        BaseDataset.__init__(self, opt)
        self.opt = opt
        self.device = (
            torch.device(f'cuda:{opt.gpu_ids[0]}')
            if opt.gpu_ids
            else torch.device('cpu')
        )

        self.root = opt.dataroot
        self.labels = np.load(f'{self.root}/ldmks.pkl')
        self.dir = os.path.join(opt.dataroot)
        self.classes, self.class_to_idx = self.find_classes(self.dir)
        self.paths = self.make_dataset_by_class(self.dir, self.class_to_idx, opt.phase)
        self.nclasses = len(self.classes)
        self.size = len(self.paths)
        self.get_mean_std()
        # modify for network later.
        opt.nclasses = self.nclasses
        opt.input_nc = self.ninput_channels

    def __getitem__(self, index):
        path = self.paths[index][0]
        label = self.paths[index][1]
        label_index = int(pathlib.Path(self.paths[index][0]).parts[2][-1]) - 1
        foldernum = pathlib.Path(path).parts[-3]
        ldmks = []
        # inefficient. change!
        #with open(self.root + '/ldmk_coords.csv', 'r') as file:
        #    reader = csv.reader(file)
        #    for row in reader:
        #        ldmks.append(row)
        #csv_idx = 0
        ldmks = self.labels
        #for i in range(len(ldmks)):
        #    if ldmks[i][0] == foldernum:
        #        csv_idx = i
        #        break
        for i in range(ldmks.shape[0]):
            if int(ldmks[i, 0, 0]) == int(foldernum):
                ldmks_idx = i
                break
        #labels = ldmks[csv_idx].numpy()
        #labels = ldmks[csv_idx][1:]
        #labels = labels.numpy()
        #label = labels[label_index]
        labels = ldmks[ldmks_idx, 1:, :]
        labels = labels.flatten() # (204,)
        mesh = Mesh(file=path, opt=self.opt, hold_history=False, export_folder=self.opt.export_folder)
        meta = {'mesh': mesh, 'label': labels, 'foldernum': foldernum}
        # get edge features
        edge_features = mesh.extract_features()
        edge_features = pad(edge_features, self.opt.ninput_edges)
        meta['edge_features'] = (edge_features - self.mean) / self.std
        return meta

    def __len__(self):
        return self.size

    # this is when the folders are organized by class...
    @staticmethod
    def find_classes(dir):
        classes = [d for d in os.listdir(dir) if os.path.isdir(os.path.join(dir, d))]
        classes.sort()
        class_to_idx = {classes[i]: i for i in range(len(classes))}
        return classes, class_to_idx

    @staticmethod
    def make_dataset_by_class(dir, class_to_idx, phase):
        meshes = []
        dir = os.path.expanduser(dir)
        for target in sorted(os.listdir(dir)):
            d = os.path.join(dir, target)
            if not os.path.isdir(d):
                continue
            for root, _, fnames in sorted(os.walk(d)):
                for fname in sorted(fnames):
                    if is_mesh_file(fname) and (root.count(phase)==1):
                        path = os.path.join(root, fname)
                        item = (path, class_to_idx[target])
                        meshes.append(item)
        return meshes
