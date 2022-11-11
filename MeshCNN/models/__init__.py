def create_model(opt):
    from .mesh_classifier import ClassifierModel # todo - get rid of this ?
    return ClassifierModel(opt)
