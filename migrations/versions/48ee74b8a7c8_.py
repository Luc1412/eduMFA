"""Add tokenowner table

Revision ID: 48ee74b8a7c8
Revises: cb6d7b7bae63
Create Date: 2019-01-09 16:58:03.968193

"""

# revision identifiers, used by Alembic.
revision = '48ee74b8a7c8'
down_revision = 'cb6d7b7bae63'

from alembic import op
import sqlalchemy as sa


def upgrade():
    try:
        op.create_table('tokenowner',
        sa.Column('id', sa.Integer(), nullable=True),
        sa.Column('token_id', sa.Integer(), nullable=True),
        sa.Column('resolver', sa.Unicode(length=120), nullable=True),
        sa.Column('resolver_type', sa.Unicode(length=120), nullable=True),
        sa.Column('user_id', sa.Unicode(length=320), nullable=True),
        sa.Column('realm_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['realm_id'], ['realm.id'], ),
        sa.ForeignKeyConstraint(['token_id'], ['token.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_tokenowner_resolver'), 'tokenowner', ['resolver'], unique=False)
        op.create_index(op.f('ix_tokenowner_user_id'), 'tokenowner', ['user_id'], unique=False)
    except Exception as exx:
        print("Can not create table 'tokenowner'. It probably already exists")
        print (exx)


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_tokenowner_user_id'), table_name='tokenowner')
    op.drop_index(op.f('ix_tokenowner_resolver'), table_name='tokenowner')
    op.drop_table('tokenowner')
    # ### end Alembic commands ###
