from ..services import normalization
from ..utils.serialization import row
class DictionaryController:
    versions=staticmethod(normalization.list_versions)
    jobs=staticmethod(normalization.list_jobs)
    @staticmethod
    def create(db,user,source_id,data):
        v,job_id=normalization.create_version(db,user,source_id,[(a.old,a.new) for a in data.aliases])
        v['backfill_job_id']=job_id
        return v
    publish=staticmethod(normalization.publish_version)
    revert=staticmethod(normalization.revert_version)
    retry=staticmethod(normalization.retry_job)
    @staticmethod
    def preview(db,user,source_id,data):
        pairs,mapping,chains,signature=normalization.validate_aliases([(a.old,a.new) for a in data.aliases])
        return {'pairs':pairs,'mapping':mapping,'chains':chains,'signature':signature}
