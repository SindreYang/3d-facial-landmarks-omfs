import os
import sys
import torch
import glob
import pickle
sys.path.append(os.path.join(os.path.dirname(__file__), "../../src/"))  # add the path to the DiffusionNet src
import diffusion_net
import numpy as np
import potpourri3d as pp3d
from pathlib import Path
from torch.utils.data import Dataset


class HeadspaceLdmksDataset(Dataset):
    def __init__(self, root_dir, train, data_format, num_landmarks, test_without_score, validate, ldmk_idx, k_eig=128,
                 use_cache=True, op_cache_dir=None):
        self.use_cache = use_cache
        self.train = train  # bool
        self.k_eig = k_eig
        self.root_dir = root_dir
        self.validate = validate
        self.cache_dir = os.path.join(root_dir, "cache", "train" if self.train else ("validation" if self.validate else "test"))
        self.op_cache_dir = op_cache_dir
        self.data_format = data_format
        self.num_landmarks = num_landmarks
        self.test_without_score = test_without_score


        # store in memory
        self.verts_list = []
        self.faces_list = []
        self.folder_num_list = []
        self.folder_num_ldmk_list = []
        self.num_samples = 0

        mesh_files = []
        # landmark_indices = [8, 27, 30, 33, 36, 39, 42, 45, 60, 64]
        # landmark = 33
        # ldmk_idx = landmark.index(landmark)

        filepattern = os.path.join('*', str(ldmk_idx), ('13*.txt' if data_format == 'pcl' else '13*.obj'))
        for filepath in glob.iglob(os.path.join(self.root_dir, ('train' if self.train else ('validation' if self.validate else 'test')), filepattern)):
            self.num_samples += 1
            mesh_files.append(filepath)
        print(f"loading {len(mesh_files)} meshes")

        # Load the actual files
        for mesh_file in mesh_files:
            print(f"loading mesh {str(mesh_file)}")
            if data_format == 'mesh':
                verts, faces = pp3d.read_mesh(mesh_file)
            else:  # 'pcl'
                verts = np.loadtxt(mesh_file, delimiter=',')



                faces = np.array([])
            folder_num = Path(mesh_file).parts[-3]
            folder_num_lmkd = Path(mesh_file).parts[-2]
            if len(verts) == 0:
                raise Exception('verts len is 0')
            # to torch
            verts = torch.tensor(np.ascontiguousarray(verts)).float()
            faces = torch.tensor(np.ascontiguousarray(faces))

            # center and unit scale
            verts = diffusion_net.geometry.normalize_positions(verts)

            self.folder_num_list.append(folder_num)
            self.folder_num_ldmk_list.append(folder_num_lmkd)

            # if this file is not cached, populate
            if not os.path.isfile(
                os.path.join(self.cache_dir, f'{folder_num}_{folder_num_lmkd}.pt')
            ):
                # Precompute operators
                diffusion_net.utils.ensure_dir_exists(self.cache_dir)
                frames, massvec, L, evals, evecs, gradX, gradY = diffusion_net.geometry.populate_cache(
                    verts, faces, k_eig=self.k_eig, op_cache_dir=self.op_cache_dir)
                torch.save(
                    (verts, faces, frames, massvec, L, evals, evecs, gradX, gradY),
                    os.path.join(
                        self.cache_dir, f'{folder_num}_{folder_num_lmkd}.pt'
                    ),
                )

    def __len__(self):
        return self.num_samples

    def __getitem__(self, idx):
        folder_num = self.folder_num_list[idx]
        folder_num_ldmk = self.folder_num_ldmk_list[idx]
        path_cache = os.path.join(self.cache_dir, folder_num, folder_num_ldmk)
        verts, faces, frames, massvec, L, evals, evecs, gradX, gradY = torch.load(
            os.path.join(self.cache_dir, f'{folder_num}_{folder_num_ldmk}.pt')
        )


        # create sparse labels
        # landmark_indices = {8,27,30,33,36,39,45,42,60,64} # indices start with 1
        landmark_indices = {33}  # indices start with 1
        if not self.train and self.test_without_score:
            labels = np.array([])
        else:
            with open(os.path.join(self.root_dir, 'train' if self.train else ('validation' if self.validate else 'test'), folder_num, folder_num_ldmk,
                                   'hmap_per_class.pkl'), 'rb') as fpath:
                labels_sparse = pickle.load(fpath)
            # labels_sparse = [item for pos, item in enumerate(labels_sparse) if pos in landmark_indices]
            labels = self.labels_from_sparse(verts, labels_sparse)



        #exr = labels[36]  # vec origin
        #exl = labels[45]  # vec target

        #R = self.rotation_matrix_from_vectors(np.array([exl[0] - exr[0], exl[1] - exr[1], exl[2] - exr[2]]),
        #                                 np.array([1, 0, 0]))

        #d = np.dot(verts, R.T)

        return verts, faces, frames, massvec, L, evals, evecs, gradX, gradY, labels, folder_num, folder_num_ldmk


    def labels_from_sparse(self, verts, labels_sparse):
        # create labels from sparse representation
        labels = torch.zeros((len(verts)))
        for k in range(len(labels_sparse)):
            pos = labels_sparse[k, 0]
            act = labels_sparse[k, 1]
            labels[int(pos)] = act
        return labels


    def rotation_matrix_from_vectors(self, vec1, vec2):
        """ Find the rotation matrix that aligns vec1 to vec2
        :param vec1: A 3d "source" vector
        :param vec2: A 3d "destination" vector
        :return mat: A transform matrix (3x3) which when applied to vec1, aligns it with vec2.
        """
        a, b = (vec1 / np.linalg.norm(vec1)).reshape(3), (vec2 / np.linalg.norm(vec2)).reshape(3)
        v = np.cross(a, b)
        c = np.dot(a, b)
        s = np.linalg.norm(v)
        kmat = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        rotation_matrix = np.eye(3) + kmat + kmat.dot(kmat) * ((1 - c) / (s ** 2))