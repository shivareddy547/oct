module Api
  class ContactsController < ApplicationController
    def create
      @contact = Contact.new(contact_params)
      
      if @contact.save
        render json: { message: 'Contact created successfully' }, status: :created
      else
        render json: { errors: @contact.errors.full_messages }, status: :unprocessable_entity
      end
    end

    private

    def contact_params
      params.require(:contact).permit(:name, :email, :description)
    end
  end
end
