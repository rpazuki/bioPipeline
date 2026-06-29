
import logging


def get_property(property_name:str, instance):
    """
    Get the property value from the dataclass instance.
    """
    logging.info("Function bio-pipeline-manager.pipeline.utils.get_property is started")
    value = getattr(instance, property_name)
    logging.info("Function bio-pipeline-manager.pipeline.utils.get_property is finished")
    return value

def get_function(function_name:str, instance, *args, **kwargs):
    """
    Get the function's return value from the dataclass instance.
    """
    logging.info("Function bio-pipeline-manager.pipeline.utils.get_function is started")
    value = getattr(instance, function_name)
    logging.info("Function bio-pipeline-manager.pipeline.utils.get_function is finished")
    return value(*args, **kwargs)
    