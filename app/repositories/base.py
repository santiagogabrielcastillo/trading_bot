"""
Base repository interface for data access operations.

Provides generic CRUD operations that can be extended by specific repositories.
"""
from abc import ABC, abstractmethod
from typing import TypeVar, Generic, List, Optional, Type
from sqlalchemy.orm import Session

from app.core.database import Base

# Generic type for model class
T = TypeVar('T', bound=Base)


class BaseRepository(ABC, Generic[T]):
    """
    Generic repository interface for database operations.
    
    Provides common CRUD operations that can be inherited and extended
    by specific repositories.
    """
    
    def __init__(self, model: Type[T], session: Session):
        """
        Initialize repository with model class and database session.
        
        Args:
            model: SQLAlchemy model class
            session: Database session
        """
        self.model = model
        self.session = session
    
    def create(self, **kwargs) -> T:
        """
        Create a new instance of the model.
        
        Args:
            **kwargs: Field values for the new instance
            
        Returns:
            Created model instance
        """
        instance = self.model(**kwargs)
        self.session.add(instance)
        self.session.flush()  # Flush to get ID without committing
        return instance
    
    def get_by_id(self, id_value) -> Optional[T]:
        """
        Retrieve a single instance by primary key.
        
        Args:
            id_value: Primary key value
            
        Returns:
            Model instance or None if not found
        """
        return self.session.query(self.model).filter(self.model.id == id_value).first()
    
    def get_all(self, limit: Optional[int] = None) -> List[T]:
        """
        Retrieve all instances, optionally limited.
        
        Args:
            limit: Maximum number of records to return
            
        Returns:
            List of model instances
        """
        query = self.session.query(self.model)
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def update(self, instance: T, **kwargs) -> T:
        """
        Update an existing instance.
        
        Args:
            instance: Model instance to update
            **kwargs: Fields to update
            
        Returns:
            Updated model instance
        """
        for key, value in kwargs.items():
            setattr(instance, key, value)
        self.session.flush()
        return instance
    
    def delete(self, instance: T) -> None:
        """
        Delete an instance.
        
        Args:
            instance: Model instance to delete
        """
        self.session.delete(instance)
        self.session.flush()
    
    @abstractmethod
    def get_by_symbol(self, symbol: str, limit: Optional[int] = None) -> List[T]:
        """
        Retrieve instances by trading symbol.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT')
            limit: Maximum number of records
            
        Returns:
            List of model instances
        """
        pass
    
    @abstractmethod
    def get_latest(self, symbol: Optional[str] = None, limit: int = 10) -> List[T]:
        """
        Retrieve the most recent instances.
        
        Args:
            symbol: Optional symbol filter
            limit: Maximum number of records
            
        Returns:
            List of model instances ordered by timestamp (most recent first)
        """
        pass

