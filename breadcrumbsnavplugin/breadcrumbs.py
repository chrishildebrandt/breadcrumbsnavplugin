from trac.core import Component, implements, TracError
from trac.config import Option, IntOption, ListOption
from trac.web import IRequestFilter
from trac.wiki import parse_args
from trac.web.chrome import ITemplateProvider, add_stylesheet
from pkg_resources import resource_filename
from trac.web.api import ITemplateStreamFilter
from genshi.builder import tag
from genshi.filters.transform import Transformer
import re, cPickle
from trac.env import IEnvironmentSetupParticipant

class BreadCrumbsSystem(Component):
    implements(IRequestFilter, ITemplateProvider, ITemplateStreamFilter, IEnvironmentSetupParticipant)
    
    ignore_pattern = Option('breadcrumbs', 'ignore pattern', None, 
        doc="""Resource names that match this pattern will not be added to 
        the breadcrumbs trail.""")
    
    max_crumbs = IntOption('breadcrumbs', 'max_crumbs', 6, 
        doc="""Indicates the maximum number of breadcrumbs to store per user.""")
    
    supported_paths = ListOption('breadcrumbs', 'paths', '/wiki*,/ticket*,/milestone*',
        doc='List of URL paths to allow breadcrumb tracking. Globs are supported.')
    
    compiled_ignore_pattern = None
    
    ## IEnvironmentSetupParticipant
    def environment_created(self):
        self._upgrade_db(self.env.get_db_cnx())

    def environment_needs_upgrade(self, db):
        cursor = db.cursor()

        try:
            cursor.execute(
                "SELECT count(*) FROM session_attribute WHERE name = %s", 
                ("breadcrumbs list",)
            )
            result = cursor.fetchone()
            if int(result[0]):
                return True
                
            return False
        except:
            db.rollback()
            return True

    def upgrade_environment(self, db):
        self._upgrade_db(db)

    def _upgrade_db(self, db):
        try:
            from trac.db import DatabaseManager
            db_backend, _ = DatabaseManager(self.env)._get_connector()            

            cursor = db.cursor()
            cursor.execute("DELETE FROM session_attribute WHERE name = %s", ("breadcrumbs list",))

        except Exception, e:
            db.rollback()
            self.log.error(e, exc_info=True)
            raise TracError(str(e))
    
    
    ## IRequestFilter
    
    def pre_process_request(self, req, handler):
        return handler
        
    def _get_crumbs(self, sess):
        crumbs = []
        if 'breadcrumbs_list' in sess:
            raw = sess['breadcrumbs_list']
            try:
                crumbs = cPickle.loads(raw.encode('ascii', 'ignore'))
            except:
                del sess['breadcrumbs_list']
        
        return crumbs
        
    def post_process_request(self, req, template, data, content_type):
        if self.compiled_ignore_pattern is None and self.ignore_pattern:
            self.compiled_ignore_pattern = re.compile(self.ignore_pattern)
        
        path = req.path_info
        try:
            if path.count('/') >= 2:
                _, realm, resource = path.split('/', 2)
            
                supported = False
            
                for pattern in self.supported_paths:
                    if re.match(pattern, path):
                        supported = True
                        break
                
                if not supported or (self.compiled_ignore_pattern and
                            self.compiled_ignore_pattern.match(resource)):
                    return template, data, content_type
                
                if '&' in resource:
                    resource = resource[0:resource.index('&')]
                
                sess = req.session
                crumbs = self._get_crumbs(sess)
                
                current = '/'.join( (realm, resource) )
                if current in crumbs:
                    crumbs.remove(current)
                    crumbs.insert(0, current)
                else:
                    crumbs.insert(0, current)
                    crumbs = crumbs[0:self.max_crumbs]
                    
                sess['breadcrumbs_list'] = cPickle.dumps(crumbs)
        except:
            self.log.exception("Breadcrumb failed :(")
        
        
        return template, data, content_type
    
    ## ITemplateProvider
    
    def get_htdocs_dirs(self):
        from pkg_resources import resource_filename
        return [('breadcrumbs', resource_filename(__name__, 'htdocs'))]
          
    def get_templates_dirs(self):
        return []

    ## ITemplateStreamFilter
    
    def filter_stream(self, req, method, filename, stream, data):
        crumbs = self._get_crumbs(req.session)
        if not crumbs:
            return stream
            
        add_stylesheet(req, 'breadcrumbs/css/breadcrumbs.css')
        li = []

        href = req.href(req.base_path)
        
        for crumb in crumbs:
            realm, resource = crumb.split('/', 1)
            name = resource.replace('_', ' ')

            if realm == "ticket":
                name = "#" + resource
            elif realm != "wiki":
                name = "%s:%s" % (realm, name)

            link = req.href(realm, resource)
            
            li.append(
                tag.li(
                    tag.a(title=name, href=link,
                    )(name)
                )
            )
            
        insert = tag.ul(class_="nav", id="breadcrumbs")(("Breadcrumbs:"), li)

        return stream | Transformer('//div[@id="metanav"]/ul').after(insert)
        