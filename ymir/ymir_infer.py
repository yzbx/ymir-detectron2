import os.path as osp
import sys
import warnings
from typing import Any, List

import cv2
import numpy as np
from easydict import EasyDict as edict
from nptyping import NDArray, Shape
from tqdm import tqdm

from detectron2.engine.defaults import DefaultPredictor
from detectron2.config import get_cfg
from ymir.utils import (YmirStage, get_merged_config,
                                   get_weight_file, get_ymir_process, CV_IMAGE)
from ymir_exc import dataset_reader as dr
from ymir_exc import env, monitor
from ymir_exc import result_writer as rw

DETECTION_RESULT = NDArray[Shape['*,5'], Any]


def get_config_file(cfg):
    model_dir = cfg.ymir.input.models_dir
    config_file = osp.join(model_dir, 'config.yaml')

    if osp.exists(config_file):
        return config_file
    else:
        raise Exception(
            f'no config_file config.yaml found in {model_dir}')



class YmirModel(object):
    def __init__(self, ymir_cfg: edict):
        self.ymir_cfg = ymir_cfg
        self.class_names = ymir_cfg.param.class_names
        if ymir_cfg.ymir.run_mining and ymir_cfg.ymir.run_infer:
            # mining_task_idx = 0
            infer_task_idx = 1
            task_num = 2
        else:
            # mining_task_idx = 0
            infer_task_idx = 0
            task_num = 1

        self.task_idx=infer_task_idx
        self.task_num=task_num

        # Specify the path to model config and checkpoint file
        config_file = get_config_file(ymir_cfg)
        checkpoint_file = get_weight_file(ymir_cfg)
        conf = ymir_cfg.param.conf_threshold

        cfg_node = get_cfg()
        cfg_node.merge_from_file(config_file)

        # TODO cfg_node.merge_from_list(cfg.param.opts)
        cfg_node.MODEL.WEIGHTS=checkpoint_file

        # Set score_threshold for builtin models
        cfg_node.MODEL.RETINANET.SCORE_THRESH_TEST = conf
        cfg_node.MODEL.ROI_HEADS.SCORE_THRESH_TEST = conf
        cfg_node.MODEL.PANOPTIC_FPN.COMBINE.INSTANCES_CONFIDENCE_THRESH = conf
        cfg_node.freeze()
        self.predictor = DefaultPredictor(cfg_node)

    def infer(self, img: CV_IMAGE) -> List[rw.Annotation]:
        """
        boxes: Nx4 of XYXY_ABS --> predictions.pred_boxes
        scores --> predictions.scores
        classes --> predictions.pred_classes.tolist()
        """
        predictions = self.predictor(img)['instances']
        anns = []

        print(predictions.scores)
        print(predictions.pred_classes)
        for i in range(len(predictions)):
            print(predictions.pred_boxes[i].tensor)
            xmin, ymin, xmax, ymax = predictions.pred_boxes[i].tensor[0].tolist()
            conf = predictions.scores[i]
            cls = predictions.pred_classes[i]
            print(conf, cls)
            ann = rw.Annotation(class_name=self.class_names[min(int(cls),len(self.class_names)-1)], score=float(conf), box=rw.Box(
                x=int(xmin), y=int(ymin), w=int(xmax - xmin), h=int(ymax - ymin)))

            anns.append(ann)
            break
        return anns

if __name__ == '__main__':
    cfg = get_merged_config()

    cfg.ymir.run_infer=True
    cfg.ymir.run_mining=False
    task_idx = 0
    task_num = 1
    m = YmirModel(ymir_cfg=cfg)

    monitor.write_monitor_logger(percent=get_ymir_process(
        stage=YmirStage.PREPROCESS, p=1.0, task_idx=task_idx, task_num=task_num))

    N = dr.items_count(env.DatasetType.CANDIDATE)
    infer_result = dict()
    model = YmirModel(cfg)
    idx = -1

    monitor_gap = max(1, N // 100)
    for asset_path, _ in tqdm(dr.item_paths(dataset_type=env.DatasetType.CANDIDATE)):
        img = cv2.imread(asset_path)
        result = model.infer(img)
        infer_result[asset_path] = result
        idx += 1

        if idx % monitor_gap == 0:
            percent = get_ymir_process(stage=YmirStage.TASK, p=idx / N, task_idx=task_idx, task_num=task_num)
            monitor.write_monitor_logger(percent=percent)

    rw.write_infer_result(infer_result=infer_result)
    monitor.write_monitor_logger(percent=get_ymir_process(
        stage=YmirStage.PREPROCESS, p=1.0, task_idx=task_idx, task_num=task_num))

