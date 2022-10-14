import numpy as np
import os 
import glob
import json
import cv2
import re 
import torch
from natsort import natsort_keygen, ns
from utils.xyz import rays_single_cam


def load_data(path):
	"""
	Assume path has the following structure - 
	path/ -
	  test/
	  train/
	  val/
	  transforms_test.json
	  transforms_train.json
	  transforms_val.json

	Assumes that frames are ordered in the json files 

	Returns:
	  samples {'train':train, 'test': test, 'val': val}
	  cam_params [H, W, f]
	"""

	train_path = os.path.join(path, 'train')
	test_path = os.path.join(path, 'test') 
	val_path = os.path.join(path, 'val')
	
	sk = natsort_keygen(alg=ns.IGNORECASE)

	train_img_paths = glob.glob(os.path.join(train_path,'*'))
	val_img_paths = glob.glob(os.path.join(val_path,'*'))
	test_img_paths = [os.path.join(test_path,fname) for fname in os.listdir(test_path) if re.match(r"r_[0-9]+.png", fname)]
	test_depth_paths = glob.glob(os.path.join(test_path,'r_*_depth*'))
	test_normal_paths = glob.glob(os.path.join(test_path, 'r_*_normal*'))

	train_img_paths.sort(key=sk)
	val_img_paths.sort(key=sk)
	test_img_paths.sort(key=sk)
	test_depth_paths.sort(key=sk)
	test_normal_paths.sort(key=sk)
	
	with open(os.path.join(path, 'transforms_train.json')) as f:
		train_transform = json.load(f)
	with open(os.path.join(path, 'transforms_test.json')) as f:
		test_transform = json.load(f)
	with open(os.path.join(path, 'transforms_val.json')) as f:
		val_transform = json.load(f)

	num_train = len(train_img_paths)
	num_val = len(val_img_paths)
	num_test = len(test_img_paths)

	## generate training samples 
	train_samples = []
	for i in range(num_train):
		train_img = cv2.cvtColor(cv2.imread(train_img_paths[i]), cv2.COLOR_BGR2RGB) / 255.0
		metadata = train_transform['frames'][i]
		transform = torch.from_numpy(np.array(metadata['transform_matrix'])).float()
		train_samples.append({'img': train_img, 'transform':transform, 'metadata':metadata})

	## generate val samples 
	val_samples = [] 
	for i in range(num_val):
		val_img = cv2.cvtColor(cv2.imread(val_img_paths[i]), cv2.COLOR_BGR2RGB) / 255.0
		metadata = val_transform['frames'][i]
		transform = torch.from_numpy(np.array(metadata['transform_matrix'])).float()
		val_samples.append({'img': val_img, 'transform':transform, 'metadata':metadata})
	

	test_samples = [] 
	for i in range(num_test):
		img = cv2.cvtColor(cv2.imread(test_img_paths[i]), cv2.COLOR_BGR2RGB) / 255.0
		img_depth = cv2.cvtColor(cv2.imread(test_depth_paths[i]), cv2.COLOR_BGR2RGB) / 255.0
		img_normal = cv2.cvtColor(cv2.imread(test_normal_paths[i]), cv2.COLOR_BGR2RGB) / 255.0
		metadata = test_transform['frames'][i]
		transform = torch.from_numpy(np.array(metadata['transform_matrix'])).float()
		test_samples.append({'img': img, 'img_depth': img_depth, 'img_normal':img_normal, 'transform':transform, 'metadata':metadata})	

	## calculate image params and focal length 
	fov = train_transform['camera_angle_x']
	H, W = img.shape[:2]
	f = W /(2 * np.tan(fov/2))
	cam_params = [H,W,f]

	## TODO: Implement half res image loading 
	samples = {} 
	samples['train'] = train_samples
	samples['test'] = test_samples
	samples['val'] = val_samples
	return samples, cam_params   

def rays_dataset(samples, cam_params):
	""" Generates rays and camera origins for train test and val sets under diff camera poses""" 
	keys = ['train', 'test', 'val']
	rays_1_cam = rays_single_cam(cam_params)
	rays = {}
	cam_origins = {}
	H, W, f = cam_params
	for k in keys:
		num_images = len(samples[k])
		transf_mats = torch.stack([s['transform'] for s in samples[k]])
		rays_dataset =  torch.matmul(transf_mats[:,:3,:3], rays_1_cam)
		cam_origins = transf_mats[:,:3,3:]
		cam_origins = cam_origins.expand(num_images,3,H*W) #Bx3xHW
		rays[k] = torch.cat((cam_origins, rays_dataset),dim=1).permute(1,0,2).reshape(6,-1) # 6xBHW, number of cameras 

	return rays

class RayGenerator:
	def __init__(self, path, on_gpu=False):
		samples, cam_params = load_data(path)
		self.samples = samples
		self.cam_params = cam_params
		self.H = cam_params[0]
		self.W = cam_params[1]
		self.f = cam_params[2]
		self.rays_dataset = rays_dataset(self.samples, cam_params)

	def select(self, mode='train', N=4096):
		""" randomly selects N train/test/val rays
		Args:
			mode: 'train', 'test', 'val'
			N: number of rays to sample 
		Returns:
			rays (torch Tensor): Nx6 
			ray_ids: Nx1 
		"""
		data = self.rays_dataset[mode]
		samples = self.samples[mode]
		ray_ids = torch.randint(0, data.size(1), (N,))
		rays = data[:,ray_ids].transpose(1,0)
		return rays, ray_ids 

		
		



