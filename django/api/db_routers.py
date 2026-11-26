# Alias do banco independente que guarda apenas os avisos de vazamento.
VAZAMENTO_DB = 'leaks'


class VazamentoRouter:
    """Isola os avisos de vazamento em um banco independente.

    O banco 'leaks' é separado do banco da aplicação porque a restauração de um
    backup do banco principal é justamente o que acontece depois de um
    vazamento: se o incidente ficasse no banco restaurado, o próprio registro
    do vazamento seria perdido. Somente o model ``Vazamento`` é lido/escrito
    nesse alias; todos os demais models continuam no banco 'default'.
    """

    vazamento_db = VAZAMENTO_DB
    vazamento_model = 'vazamento'

    @classmethod
    def _eh_vazamento(cls, model):
        return model._meta.model_name == cls.vazamento_model

    def db_for_read(self, model, **hints):
        if self._eh_vazamento(model):
            return self.vazamento_db
        return None

    def db_for_write(self, model, **hints):
        if self._eh_vazamento(model):
            return self.vazamento_db
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if self._eh_vazamento(obj1._meta.model) or self._eh_vazamento(obj2._meta.model):
            return obj1._meta.model is obj2._meta.model
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if model_name == self.vazamento_model:
            return db == self.vazamento_db
        if db == self.vazamento_db:
            return False
        return None


class TombstoneRouter:
    """Isola o registro de usuários deletados em um banco independente.

    O banco 'tombstones' é deliberadamente separado do banco da aplicação e do
    banco do Keycloak: restaurar um backup da aplicação ou do Keycloak não pode
    sobrescrever a lista de usuários deletados. Somente o model
    ``UsuarioDeletado`` é lido/escrito nesse alias; todos os demais models
    continuam no banco 'default'.
    """

    tombstone_db = 'tombstones'
    tombstone_model = 'usuariodeletado'

    @classmethod
    def _eh_tombstone(cls, model):
        return model._meta.model_name == cls.tombstone_model

    def db_for_read(self, model, **hints):
        if self._eh_tombstone(model):
            return self.tombstone_db
        return None

    def db_for_write(self, model, **hints):
        if self._eh_tombstone(model):
            return self.tombstone_db
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if self._eh_tombstone(obj1._meta.model) or self._eh_tombstone(obj2._meta.model):
            return obj1._meta.model is obj2._meta.model
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if model_name == self.tombstone_model:
            return db == self.tombstone_db
        if db == self.tombstone_db:
            return False
        return None
