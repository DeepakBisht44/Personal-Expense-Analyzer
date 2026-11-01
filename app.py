import os, secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, extract

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-development-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'mysql+pymysql://expense_user:expense_password@db:3306/expense_analyzer')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(60), nullable=False)
    kind = db.Column(db.Enum('income', 'expense', name='category_kind'), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'name', 'kind', name='uq_user_category'),)

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    kind = db.Column(db.Enum('income', 'expense', name='transaction_kind'), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    description = db.Column(db.String(255), default='')
    transaction_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    category = db.relationship('Category')

class Budget(db.Model):
    __tablename__ = 'budgets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    month = db.Column(db.String(7), nullable=False) # YYYY-MM
    limit_amount = db.Column(db.Numeric(12, 2), nullable=False)
    category = db.relationship('Category')
    __table_args__ = (db.UniqueConstraint('user_id', 'category_id', 'month', name='uq_user_budget_month'),)

class SavingsGoal(db.Model):
    __tablename__ = 'savings_goals'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    target_amount = db.Column(db.Numeric(12, 2), nullable=False)
    saved_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    target_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

@login_manager.user_loader
def load_user(user_id): return db.session.get(User, int(user_id))

@app.before_request
def ensure_csrf_token():
    if 'csrf_token' not in session: session['csrf_token'] = secrets.token_hex(32)

def csrf_protect(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
        if not token or token != session.get('csrf_token'):
            return jsonify({'error': 'Invalid or missing security token. Refresh the page and try again.'}), 400
        return fn(*args, **kwargs)
    return wrapped

def money(value): return float(value or 0)
def json_transaction(t):
    return {'id': t.id, 'kind': t.kind, 'amount': money(t.amount), 'description': t.description or '',
            'date': t.transaction_date.isoformat(), 'category_id': t.category_id, 'category': t.category.name}
def parse_amount(value):
    try: amount = Decimal(str(value))
    except (InvalidOperation, TypeError): raise ValueError('Enter a valid amount.')
    if not amount.is_finite() or amount <= 0 or amount > Decimal('9999999999.99'): raise ValueError('Amount must be greater than zero and within the supported limit.')
    return amount.quantize(Decimal('0.01'))
def owned_category(category_id, kind=None):
    q = Category.query.filter_by(id=category_id, user_id=current_user.id)
    if kind: q = q.filter_by(kind=kind)
    return q.first()
def month_bounds(month):
    try:
        y, m = map(int, month.split('-'))
        if len(month) != 7 or not 1 <= m <= 12: raise ValueError
        return date(y, m, 1), date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    except Exception: raise ValueError('Month must use YYYY-MM format.')

def seed_categories(user):
    defaults = [('Salary','income'),('Freelance','income'),('Investment','income'),('Other income','income'),
                ('Food','expense'),('Transport','expense'),('Shopping','expense'),('Bills','expense'),('Education','expense'),('Health','expense'),('Entertainment','expense'),('Other expense','expense')]
    for name, kind in defaults: db.session.add(Category(user_id=user.id, name=name, kind=kind))

@app.route('/')
def index(): return redirect(url_for('dashboard' if current_user.is_authenticated else 'login'))
@app.route('/register', methods=['GET','POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name, email, password = request.form.get('name','').strip(), request.form.get('email','').strip().lower(), request.form.get('password','')
        if len(name) < 2 or len(name) > 100: flash('Please enter a name between 2 and 100 characters.', 'error')
        elif '@' not in email or len(email) > 255: flash('Enter a valid email address.', 'error')
        elif len(password) < 8: flash('Password must contain at least 8 characters.', 'error')
        elif User.query.filter_by(email=email).first(): flash('An account with this email already exists.', 'error')
        else:
            user = User(name=name, email=email); user.set_password(password); db.session.add(user); db.session.flush(); seed_categories(user); db.session.commit()
            login_user(user); flash('Account created. Welcome to your expense dashboard!', 'success'); return redirect(url_for('dashboard'))
    return render_template('auth.html', mode='register')
@app.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower(); password = request.form.get('password','')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password): login_user(user, remember=False); return redirect(url_for('dashboard'))
        flash('Incorrect email or password.', 'error')
    return render_template('auth.html', mode='login')
@app.post('/logout')
@login_required
@csrf_protect
def logout(): logout_user(); session.clear(); return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    categories = Category.query.filter_by(user_id=current_user.id).order_by(Category.kind, Category.name).all()
    return render_template('dashboard.html', categories=categories)

@app.get('/api/summary')
@login_required
def summary():
    month = request.args.get('month', date.today().strftime('%Y-%m'))
    try: start, end = month_bounds(month)
    except ValueError as e: return jsonify({'error': str(e)}), 400
    base = Transaction.query.filter(Transaction.user_id == current_user.id, Transaction.transaction_date >= start, Transaction.transaction_date < end)
    income = db.session.query(func.coalesce(func.sum(Transaction.amount),0)).filter(Transaction.user_id==current_user.id, Transaction.kind=='income', Transaction.transaction_date>=start, Transaction.transaction_date<end).scalar()
    expense = db.session.query(func.coalesce(func.sum(Transaction.amount),0)).filter(Transaction.user_id==current_user.id, Transaction.kind=='expense', Transaction.transaction_date>=start, Transaction.transaction_date<end).scalar()
    budgets = Budget.query.filter_by(user_id=current_user.id, month=month).all()
    budget_data=[]
    for b in budgets:
        spent = db.session.query(func.coalesce(func.sum(Transaction.amount),0)).filter(Transaction.user_id==current_user.id, Transaction.category_id==b.category_id, Transaction.kind=='expense', Transaction.transaction_date>=start, Transaction.transaction_date<end).scalar()
        budget_data.append({'category':b.category.name,'limit':money(b.limit_amount),'spent':money(spent),'percent':min(100, round(money(spent)/money(b.limit_amount)*100)) if b.limit_amount else 0})
    cat_rows = db.session.query(Category.name, func.sum(Transaction.amount)).join(Transaction, Transaction.category_id==Category.id).filter(Transaction.user_id==current_user.id, Category.user_id==current_user.id, Transaction.kind=='expense', Transaction.transaction_date>=start, Transaction.transaction_date<end).group_by(Category.name).all()
    monthly=[]
    for offset in range(5,-1,-1):
        idx = start.year*12 + start.month-1 - offset; y,m = divmod(idx,12); m += 1
        s=date(y,m,1); e=date(y+(m==12),1 if m==12 else m+1,1)
        inc=db.session.query(func.coalesce(func.sum(Transaction.amount),0)).filter(Transaction.user_id==current_user.id,Transaction.kind=='income',Transaction.transaction_date>=s,Transaction.transaction_date<e).scalar()
        exp=db.session.query(func.coalesce(func.sum(Transaction.amount),0)).filter(Transaction.user_id==current_user.id,Transaction.kind=='expense',Transaction.transaction_date>=s,Transaction.transaction_date<e).scalar()
        monthly.append({'month':s.strftime('%b %y'),'income':money(inc),'expense':money(exp)})
    goals= SavingsGoal.query.filter_by(user_id=current_user.id).order_by(SavingsGoal.created_at.desc()).all()
    recent=Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.transaction_date.desc(),Transaction.id.desc()).limit(6).all()
    return jsonify({'month':month,'income':money(income),'expense':money(expense),'balance':money(income)-money(expense),'savings_rate':round((money(income)-money(expense))/money(income)*100,1) if money(income)>0 else 0,
      'category_labels':[r[0] for r in cat_rows],'category_values':[money(r[1]) for r in cat_rows],'monthly':monthly,'budgets':budget_data,
      'goals':[{'id':g.id,'title':g.title,'target':money(g.target_amount),'saved':money(g.saved_amount),'percent':min(100,round(money(g.saved_amount)/money(g.target_amount)*100)) if g.target_amount else 0,'target_date':g.target_date.isoformat() if g.target_date else None} for g in goals],
      'recent':[json_transaction(t) for t in recent]})

@app.get('/api/categories')
@login_required
def categories_api():
    cats=Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all()
    return jsonify([{'id':c.id,'name':c.name,'kind':c.kind} for c in cats])
@app.post('/api/categories')
@login_required
@csrf_protect
def add_category():
    data=request.get_json(silent=True) or {}; name=str(data.get('name','')).strip(); kind=data.get('kind')
    if not 2<=len(name)<=60 or kind not in ('income','expense'): return jsonify({'error':'Enter a category name (2–60 characters) and valid type.'}),400
    if Category.query.filter_by(user_id=current_user.id,name=name,kind=kind).first(): return jsonify({'error':'That category already exists.'}),409
    c=Category(user_id=current_user.id,name=name,kind=kind); db.session.add(c); db.session.commit(); return jsonify({'id':c.id,'name':c.name,'kind':c.kind}),201

@app.get('/api/transactions')
@login_required
def list_transactions():
    q=Transaction.query.filter_by(user_id=current_user.id)
    kind=request.args.get('kind'); month=request.args.get('month'); search=request.args.get('search','').strip()
    if kind in ('income','expense'): q=q.filter_by(kind=kind)
    if month:
        try: s,e=month_bounds(month); q=q.filter(Transaction.transaction_date>=s,Transaction.transaction_date<e)
        except ValueError as ex: return jsonify({'error':str(ex)}),400
    if search: q=q.filter(Transaction.description.ilike(f'%{search[:80]}%'))
    rows=q.order_by(Transaction.transaction_date.desc(),Transaction.id.desc()).limit(200).all()
    return jsonify([json_transaction(t) for t in rows])
@app.post('/api/transactions')
@login_required
@csrf_protect
def create_transaction():
    data=request.get_json(silent=True) or {}; kind=data.get('kind'); category=owned_category(data.get('category_id'),kind)
    if kind not in ('income','expense') or not category: return jsonify({'error':'Choose a category belonging to your account and matching the transaction type.'}),400
    try: amount=parse_amount(data.get('amount')); tx_date=date.fromisoformat(data.get('date',''))
    except (ValueError,TypeError) as e: return jsonify({'error':str(e) or 'Enter a valid date.'}),400
    if tx_date>date.today(): return jsonify({'error':'Future transaction dates are not allowed.'}),400
    desc=str(data.get('description','')).strip()[:255]
    t=Transaction(user_id=current_user.id,category_id=category.id,kind=kind,amount=amount,transaction_date=tx_date,description=desc)
    db.session.add(t); db.session.commit(); return jsonify(json_transaction(t)),201
@app.put('/api/transactions/<int:tx_id>')
@login_required
@csrf_protect
def update_transaction(tx_id):
    t=Transaction.query.filter_by(id=tx_id,user_id=current_user.id).first_or_404(); data=request.get_json(silent=True) or {}
    kind=data.get('kind',t.kind); category=owned_category(data.get('category_id',t.category_id),kind)
    if kind not in ('income','expense') or not category: return jsonify({'error':'Invalid category for this transaction.'}),400
    try: amount=parse_amount(data.get('amount',t.amount)); tx_date=date.fromisoformat(data.get('date',t.transaction_date.isoformat()))
    except (ValueError,TypeError) as e: return jsonify({'error':str(e)}),400
    if tx_date>date.today(): return jsonify({'error':'Future transaction dates are not allowed.'}),400
    t.kind=kind;t.category_id=category.id;t.amount=amount;t.transaction_date=tx_date;t.description=str(data.get('description',t.description)).strip()[:255]
    db.session.commit();return jsonify(json_transaction(t))
@app.delete('/api/transactions/<int:tx_id>')
@login_required
@csrf_protect
def delete_transaction(tx_id):
    t=Transaction.query.filter_by(id=tx_id,user_id=current_user.id).first_or_404();db.session.delete(t);db.session.commit();return jsonify({'success':True})

@app.get('/api/budgets')
@login_required
def list_budgets():
    month=request.args.get('month',date.today().strftime('%Y-%m'))
    try:s,e=month_bounds(month)
    except ValueError as ex:return jsonify({'error':str(ex)}),400
    rows=Budget.query.filter_by(user_id=current_user.id,month=month).all();out=[]
    for b in rows:
        spent=db.session.query(func.coalesce(func.sum(Transaction.amount),0)).filter(Transaction.user_id==current_user.id,Transaction.category_id==b.category_id,Transaction.kind=='expense',Transaction.transaction_date>=s,Transaction.transaction_date<e).scalar()
        out.append({'id':b.id,'category_id':b.category_id,'category':b.category.name,'month':b.month,'limit':money(b.limit_amount),'spent':money(spent),'remaining':money(b.limit_amount)-money(spent)})
    return jsonify(out)
@app.post('/api/budgets')
@login_required
@csrf_protect
def save_budget():
    data=request.get_json(silent=True) or {};cat=owned_category(data.get('category_id'),'expense');month=data.get('month',date.today().strftime('%Y-%m'))
    if not cat:return jsonify({'error':'Choose one of your expense categories.'}),400
    try:month_bounds(month);amount=parse_amount(data.get('limit'))
    except ValueError as ex:return jsonify({'error':str(ex)}),400
    b=Budget.query.filter_by(user_id=current_user.id,category_id=cat.id,month=month).first()
    if b:b.limit_amount=amount
    else:b=Budget(user_id=current_user.id,category_id=cat.id,month=month,limit_amount=amount);db.session.add(b)
    db.session.commit();return jsonify({'id':b.id,'category':cat.name,'limit':money(b.limit_amount),'month':month}),201
@app.delete('/api/budgets/<int:budget_id>')
@login_required
@csrf_protect
def delete_budget(budget_id):
    b=Budget.query.filter_by(id=budget_id,user_id=current_user.id).first_or_404();db.session.delete(b);db.session.commit();return jsonify({'success':True})

@app.get('/api/goals')
@login_required
def list_goals():
    return jsonify([{'id':g.id,'title':g.title,'target':money(g.target_amount),'saved':money(g.saved_amount),'target_date':g.target_date.isoformat() if g.target_date else ''} for g in SavingsGoal.query.filter_by(user_id=current_user.id).order_by(SavingsGoal.created_at.desc()).all()])
@app.post('/api/goals')
@login_required
@csrf_protect
def create_goal():
    data=request.get_json(silent=True) or {};title=str(data.get('title','')).strip()
    if not 2<=len(title)<=120:return jsonify({'error':'Goal title must be 2–120 characters.'}),400
    try:target=parse_amount(data.get('target'));saved=Decimal(str(data.get('saved',0))).quantize(Decimal('0.01'))
    except (ValueError,InvalidOperation,TypeError) as ex:return jsonify({'error':str(ex)}),400
    if not saved.is_finite() or saved<0 or saved>target:return jsonify({'error':'Saved amount must be between zero and the target.'}),400
    try:target_date=date.fromisoformat(data['target_date']) if data.get('target_date') else None
    except ValueError:return jsonify({'error':'Enter a valid target date.'}),400
    g=SavingsGoal(user_id=current_user.id,title=title,target_amount=target,saved_amount=saved,target_date=target_date);db.session.add(g);db.session.commit();return jsonify({'id':g.id,'title':g.title}),201
@app.put('/api/goals/<int:goal_id>')
@login_required
@csrf_protect
def update_goal(goal_id):
    g=SavingsGoal.query.filter_by(id=goal_id,user_id=current_user.id).first_or_404();data=request.get_json(silent=True) or {}
    try:saved=Decimal(str(data.get('saved'))).quantize(Decimal('0.01'))
    except (InvalidOperation,TypeError):return jsonify({'error':'Enter a valid saved amount.'}),400
    if not saved.is_finite() or saved<0 or saved>g.target_amount:return jsonify({'error':'Saved amount must be between zero and the target.'}),400
    g.saved_amount=saved;db.session.commit();return jsonify({'success':True})
@app.delete('/api/goals/<int:goal_id>')
@login_required
@csrf_protect
def delete_goal(goal_id):
    g=SavingsGoal.query.filter_by(id=goal_id,user_id=current_user.id).first_or_404();db.session.delete(g);db.session.commit();return jsonify({'success':True})

@app.get('/health')
def health():
    try: db.session.execute(db.text('SELECT 1')); return jsonify({'status':'ok','database':'connected'})
    except Exception:return jsonify({'status':'error','database':'unavailable'}),503

@app.cli.command('init-db')
def init_db():
    db.create_all(); print('Database tables created.')

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0',port=5000,debug=os.getenv('FLASK_DEBUG')=='1')
